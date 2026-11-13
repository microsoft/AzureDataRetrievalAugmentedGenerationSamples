"""Explicit control-plane setup. Never imported to provision from the app/loader."""

import argparse
import json
import logging
from pathlib import Path
import shutil
import subprocess
import tempfile

CONTAINERS = {"search_qflat": "quantizedFlat", "search_diskann": "diskANN"}
logger = logging.getLogger(__name__)


def container_resource(name):
    if name not in CONTAINERS:
        raise ValueError("Only search_qflat and search_diskann are supported.")
    return {
        "id": name,
        "partitionKey": {"paths": ["/id"], "kind": "Hash"},
        "fullTextPolicy": {"defaultLanguage": "en-US",
                           "fullTextPaths": [{"path": "/text", "language": "en-US"}]},
        "vectorEmbeddingPolicy": {"vectorEmbeddings": [{
            "path": "/embedding", "dataType": "float32",
            "distanceFunction": "cosine", "dimensions": 1536}]},
        "indexingPolicy": {
            "indexingMode": "consistent", "automatic": True,
            "includedPaths": [{"path": "/*"}],
            "excludedPaths": [{"path": '/"_etag"/?'}, {"path": "/embedding/*"}],
            "vectorIndexes": [{"path": "/embedding", "type": CONTAINERS[name]}],
            "fullTextIndexes": [{"path": "/text"}],
        },
    }


def _required_path(entries, required):
    """Match required fields on one path, allowing server-added metadata."""
    if not isinstance(entries, list):
        return False
    matches = [entry for entry in entries
               if isinstance(entry, dict) and entry.get("path") == required["path"]]
    return len(matches) == 1 and all(
        matches[0].get(key) == value for key, value in required.items())


def validate_policy(resource, name):
    expected = container_resource(name)
    partition = resource.get("partitionKey", {})
    indexing = resource.get("indexingPolicy", {})
    vector = resource.get("vectorEmbeddingPolicy", {})
    full_text = resource.get("fullTextPolicy", {})
    # ARM/data-plane responses may add package/defaultSpec and quantizer fields.
    # Compare the required contract, not complete dictionaries from creation input.
    if (resource.get("id") != name or partition.get("paths") != ["/id"]
            or partition.get("kind") != "Hash"
            or not _required_path(vector.get("vectorEmbeddings"),
                                  expected["vectorEmbeddingPolicy"]["vectorEmbeddings"][0])
            or full_text.get("defaultLanguage") != "en-US"
            or not _required_path(full_text.get("fullTextPaths"),
                                  expected["fullTextPolicy"]["fullTextPaths"][0])
            or not _required_path(indexing.get("vectorIndexes"),
                                  expected["indexingPolicy"]["vectorIndexes"][0])
            or not _required_path(indexing.get("fullTextIndexes"), {"path": "/text"})
            or indexing.get("indexingMode", "").lower() != "consistent"
            or indexing.get("automatic", True) is not True
            or not _required_path(indexing.get("includedPaths"), {"path": "/*"})):
        raise ValueError(f"{name} has incompatible partition/vector/full-text policies. "
                         "Do not overwrite it. Choose a dedicated compatible database.")


def az_json(*args):
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI is required.")
    result = subprocess.run([executable, *args, "--only-show-errors", "--output", "json"],
                            capture_output=True, text=True, check=False, timeout=300)
    if result.returncode:
        # Do not echo CLI error output: it may contain private resource identifiers.
        try:
            result.check_returncode()
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("Azure CLI operation failed. Check subscription, permissions, "
                               "account capabilities and region support.") from exc
    return json.loads(result.stdout) if result.stdout.strip() else None


def setup_containers(subscription, resource_group, account, database, confirm=False):
    common = ("--subscription", subscription, "--resource-group", resource_group,
              "--account-name", account, "--database-name", database)
    # Listing must succeed. Authorization failures are NEVER interpreted as absence.
    existing = az_json("cosmosdb", "sql", "container", "list", *common)
    by_name = {entry["resource"]["id"]: entry["resource"] for entry in existing}
    # Inspect both first, before provisioning either.
    for name in CONTAINERS:
        if name in by_name:
            validate_policy(by_name[name], name)
    missing = [name for name in CONTAINERS if name not in by_name]
    if missing and not confirm:
        raise ValueError("Missing containers. Re-run with --confirm-create to create each "
                         "at 400 RU/s. No existing throughput will be changed.")
    with tempfile.TemporaryDirectory(prefix="cosmos-search-policies-") as directory:
        for name in CONTAINERS:
            if name in by_name:
                print(f"{name}: compatible, reused without throughput changes")
                continue
            resource = container_resource(name)
            files = {}
            for policy in ("indexingPolicy", "vectorEmbeddingPolicy", "fullTextPolicy"):
                path = Path(directory) / f"{name}-{policy}.json"
                path.write_text(json.dumps(resource[policy], indent=2), encoding="utf-8")
                files[policy] = "@" + str(path)
            result = az_json(
                "cosmosdb", "sql", "container", "create", *common,
                "--name", name, "--partition-key-path", "/id", "--throughput", "400",
                "--idx", files["indexingPolicy"],
                "--vector-embeddings", files["vectorEmbeddingPolicy"],
                "--full-text-policy", files["fullTextPolicy"])
            validate_policy(result["resource"], name)
            print(f"{name}: created at 400 RU/s")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("subscription", "resource-group", "account", "database"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--confirm-create", action="store_true")
    args = parser.parse_args(argv)
    try:
        setup_containers(args.subscription, args.resource_group, args.account,
                         args.database, args.confirm_create)
        return 0
    except (RuntimeError, ValueError, subprocess.TimeoutExpired):
        logger.exception("Container setup failed.")
        print("Setup failed. Check explicit targets, container policies, Azure CLI "
              "permissions and network access.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
