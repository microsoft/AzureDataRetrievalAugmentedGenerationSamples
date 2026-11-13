"""Generate private local configuration from the selected azd environment.

No Azure writes, shell evaluation, credential persistence, or global env mutation.
Requires the sample's python-dotenv dependency to preserve complete .env bindings.
"""

import argparse
import io
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit
import uuid

from dotenv.parser import parse_stream

logger = logging.getLogger(__name__)

PYTHON_KEYS = (
    "COSMOS_URI", "COSMOS_DB_DATABASE", "AZURE_AI_INFERENCE_ENDPOINT",
    "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "AZURE_OPENAI_EMBEDDING_MODEL", "AZURE_OPENAI_EMBEDDING_VERSION",
    "AZURE_OPENAI_API_VERSION",
)
DOTNET_CONTAINERS = {
    "COSMOS_DB_CONTAINER_QFLAT": "reranker_dotnet_qflat",
    "COSMOS_DB_CONTAINER_DISKANN": "reranker_dotnet_diskann",
}


def read_outputs(project_root):
    executable = shutil.which("azd")
    if not executable:
        raise RuntimeError("azd is required on PATH.")
    result = subprocess.run(
        [executable, "env", "get-values", "--output", "json"],
        cwd=project_root, capture_output=True, text=True, check=False, timeout=120,
        shell=False,
    )
    if result.returncode:
        try:
            result.check_returncode()
        except subprocess.CalledProcessError as exc:
            seen = set()
            for stream, output in (("stderr", exc.stderr), ("stdout", exc.stdout)):
                detail = (output or "").strip()
                if detail and detail not in seen:
                    logger.error("Sensitive local azd %s (do not share raw logs):\n%s",
                                 stream, detail)
                    seen.add(detail)
            raise RuntimeError("azd env get-values failed. Select a provisioned environment.") from exc
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("azd outputs are not valid JSON.") from exc


def validate_outputs(values, include_dotnet):
    if not isinstance(values, dict):
        raise ValueError("azd outputs must be a JSON object.")
    required = (
        *PYTHON_KEYS, "AZURE_ENV_NAME", "AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP",
        "COSMOS_ACCOUNT_NAME", "COSMOS_ACCOUNT_ID", "INFERENCE_ACCOUNT_NAME",
        "INFERENCE_ACCOUNT_ID",
    )
    for key in (*required, *(DOTNET_CONTAINERS if include_dotnet else ())):
        if not isinstance(values.get(key), str) or not values[key]:
            raise ValueError(f"Missing or malformed azd output: {key}.")
    environment = values["AZURE_ENV_NAME"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", environment):
        raise ValueError("Invalid AZURE_ENV_NAME output. Use 1-40 lowercase letters/digits/hyphens.")
    group = values["AZURE_RESOURCE_GROUP"]
    if group != f"rg-reranker-{environment}":
        raise ValueError("Resource group output is not the dedicated environment group.")
    account = values["COSMOS_ACCOUNT_NAME"]
    try:
        canonical = str(uuid.UUID(account))
        subscription = str(uuid.UUID(values["AZURE_SUBSCRIPTION_ID"]))
    except (ValueError, AttributeError) as exc:
        raise ValueError("Account/subscription outputs must be canonical UUIDs.") from exc
    if (account != canonical or account[0] not in "abcdef"
            or values["AZURE_SUBSCRIPTION_ID"].lower() != subscription):
        raise ValueError("Account name output must be a lowercase canonical UUID starting a-f.")
    if "AZURE_COSMOS_ACCOUNT_NAME" in values and values["AZURE_COSMOS_ACCOUNT_NAME"] != account:
        raise ValueError("Account output differs from the persisted preprovision name.")
    if values["INFERENCE_ACCOUNT_NAME"] != account:
        raise ValueError("Inference account output must match the Cosmos account name.")
    scope = f"/subscriptions/{subscription}/resourceGroups/{group}/providers"
    for key, kind in (
        ("COSMOS_ACCOUNT_ID", "Microsoft.DocumentDB/databaseAccounts"),
        ("INFERENCE_ACCOUNT_ID", "Microsoft.InferenceService/inferenceAccounts"),
    ):
        if values[key].lower() != f"{scope}/{kind}/{account}".lower():
            raise ValueError(f"Resource ID output does not match its account/group: {key}.")
    if values["COSMOS_DB_DATABASE"] != "reranker":
        raise ValueError("Database output must be reranker.")
    for key in ("COSMOS_URI", "AZURE_AI_INFERENCE_ENDPOINT", "AZURE_OPENAI_ENDPOINT"):
        endpoint = values[key]
        # Restrict syntax before serialization. No credentials, interpolation or queries.
        if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::443)?(?:/[A-Za-z0-9._~/-]*)?", endpoint):
            raise ValueError(f"Malformed HTTPS endpoint output: {key}.")
        parsed = urlsplit(endpoint)
        if not parsed.hostname or "." not in parsed.hostname or ".." in parsed.hostname:
            raise ValueError(f"Malformed endpoint host output: {key}.")
    if urlsplit(values["COSMOS_URI"]).hostname != f"{account}.documents.azure.com":
        raise ValueError("Cosmos endpoint output does not match the account.")
    if urlsplit(values["AZURE_OPENAI_ENDPOINT"]).hostname != f"aoai-{account}.openai.azure.com":
        raise ValueError("OpenAI endpoint output does not match the account.")
    for key in ("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "AZURE_OPENAI_EMBEDDING_MODEL",
                "AZURE_OPENAI_EMBEDDING_VERSION", "AZURE_OPENAI_API_VERSION"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", values[key]):
            raise ValueError(f"Malformed embedding output: {key}.")
    if include_dotnet:
        for key, expected in DOTNET_CONTAINERS.items():
            if values[key] != expected:
                raise ValueError(f"Unexpected .NET container output: {key}.")
        for key, source in (("COSMOS_DB_ENDPOINT", "COSMOS_URI"),
                            ("INFERENCE_ENDPOINT", "AZURE_AI_INFERENCE_ENDPOINT")):
            if key in values and values[key] != values[source]:
                raise ValueError(f"Inconsistent endpoint output: {key}.")
    return {key: values[key] for key in required}


def powershell_literal(value):
    return "'" + value.replace("'", "''") + "'"


def environment_script(values):
    lines = [
        "# Generated by scripts/configure_azd.py. Private, do not commit.",
        "# Dot-source in PowerShell 7, then restart apps to switch environments.",
    ]
    for key, value in values.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError("Invalid generated environment variable name.")
        lines.append(f"$env:{key} = {powershell_literal(value)}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def merge_dotenv(original, values):
    text = original.decode("utf-8-sig")
    kept = []
    for binding in parse_stream(io.StringIO(text)):
        if binding.error:
            raise ValueError("Existing .env is malformed. Fix it before regenerating config.")
        if binding.key not in values:
            kept.append(binding.original.string)
    prefix = "".join(kept)
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += "\n"
    # All managed values passed validation and contain no quotes or interpolation.
    return (prefix + "".join(f'{key}="{value}"\n' for key, value in values.items())).encode("utf-8")


def replace_files(contents):
    """Stage every file before replacing any; roll back ordinary I/O failures.

    Each replacement is atomic. A machine crash is not a multi-file transaction:
    stop apps and regenerate before continuing if a run is interrupted.
    """
    staged, backups, replaced = {}, {}, []
    try:
        for target, content in contents.items():
            if target.is_symlink():
                raise ValueError("Refusing to replace a symlinked configuration file.")
            target.parent.mkdir(parents=True, exist_ok=True)
            for data, collection in (
                (content, staged),
                (target.read_bytes() if target.exists() else None, backups),
            ):
                if data is None:
                    collection[target] = None
                    continue
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".azd-config-", delete=False) as file:
                    collection[target] = Path(file.name)
                    file.write(data)
                    file.flush()
                    os.fsync(file.fileno())
        for target, stage in staged.items():
            os.replace(stage, target)
            replaced.append(target)
    except BaseException:
        for target in reversed(replaced):
            if backups[target] is None:
                target.unlink(missing_ok=True)
            else:
                os.replace(backups[target], target)
        raise
    finally:
        for file in (*staged.values(), *backups.values()):
            if file is not None:
                file.unlink(missing_ok=True)


def configure(project_root, include_dotnet=False, values=None):
    root = Path(project_root).resolve()
    raw = read_outputs(root) if values is None else values
    validated = validate_outputs(raw, include_dotnet)
    python_root = root / "python" if include_dotnet else root
    if not python_root.is_dir():
        raise ValueError("Python project directory is missing.")
    env_file = python_root / ".env"
    if env_file.is_symlink():
        raise ValueError("Refusing to replace a symlinked .env.")
    python_values = {key: validated[key] for key in PYTHON_KEYS}
    # azd accounts are keyless, even if a previous manual configuration used a key.
    python_values["AZURE_OPENAI_AUTH_MODE"] = "entra"
    old = env_file.read_bytes() if env_file.exists() else b""
    # Parse and render everything before any directory creation or file replacement.
    contents = {env_file: merge_dotenv(old, python_values)}
    shell_values = dict(validated)
    shell_values["AZURE_OPENAI_AUTH_MODE"] = "entra"
    if include_dotnet:
        shell_values.update(
            COSMOS_DB_ENDPOINT=validated["COSMOS_URI"],
            INFERENCE_ENDPOINT=validated["AZURE_AI_INFERENCE_ENDPOINT"],
            **DOTNET_CONTAINERS,
        )
    contents[root / ".local/azd-env.ps1"] = environment_script(shell_values)
    if include_dotnet:
        contents[python_root / ".local/azd-env.ps1"] = environment_script(
            {**validated, "AZURE_OPENAI_AUTH_MODE": "entra"})
    replace_files(contents)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--include-dotnet", action="store_true")
    args = parser.parse_args()
    try:
        configure(args.project_root, args.include_dotnet)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        # Tracebacks are private terminal diagnostics, never public configuration output.
        logger.exception("Local azd configuration failed.")
        print(f"Local azd configuration failed ({type(error).__name__}). "
              "Check selected environment outputs, .env syntax and file access. "
              "No calling-shell settings were changed.")
        return 1
    print("Generated private .env and .local/azd-env.ps1. "
          "Dot-source the script in your calling shell and restart local apps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
