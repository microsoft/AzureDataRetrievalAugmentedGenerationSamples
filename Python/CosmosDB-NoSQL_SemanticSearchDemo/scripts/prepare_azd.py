"""Persist a valid shared account UUID before azd creates any Azure resources."""

import argparse
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import uuid
import requests
from azure.identity import AzureCliCredential

NAME_KEY = "AZURE_COSMOS_ACCOUNT_NAME"
NAME_PATTERN = r"[a-f][0-9a-f]{7}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
logger = logging.getLogger(__name__)


def valid_name(value):
    return isinstance(value, str) and re.fullmatch(NAME_PATTERN, value) is not None


def generate_name():
    # Accept/reject complete UUIDs. Never change UUID bytes or prepend a letter.
    for _ in range(128):
        candidate = str(uuid.uuid4())
        if valid_name(candidate):
            return candidate
    raise RuntimeError("No letter-leading UUID generated after 128 attempts. No name persisted.")


def choose_name(values, regenerate_invalid=False):
    deployed = values.get("COSMOS_ACCOUNT_NAME")
    if NAME_KEY in values:
        persisted = values[NAME_KEY]
        if valid_name(persisted):
            if valid_name(deployed) and deployed != persisted:
                raise ValueError("Persisted name and deployed Cosmos output conflict. Inspect state; do not rename.")
            candidate = persisted
        else:
            if not regenerate_invalid:
                raise ValueError("Persisted account name is invalid. Inspect the failed deployment before "
                                 "explicit --regenerate-invalid-name recovery.")
            candidate = deployed if valid_name(deployed) else generate_name()
    elif "COSMOS_ACCOUNT_NAME" in values:
        if valid_name(deployed):
            # Preserve a successful deployment made before the persisted-name hook.
            candidate = deployed
        elif regenerate_invalid:
            candidate = generate_name()
        else:
            raise ValueError("Existing Cosmos output name is invalid. Inspect the failed deployment before "
                             "explicit --regenerate-invalid-name recovery.")
    else:
        candidate = generate_name()
    inference = values.get("INFERENCE_ACCOUNT_NAME")
    if valid_name(inference) and inference != candidate:
        raise ValueError("Existing inference output and selected account name conflict. Inspect state; do not rename.")
    return candidate


def azd(executable, root, arguments):
    result = subprocess.run(
        [executable, *arguments], cwd=root, capture_output=True, text=True,
        check=False, timeout=120, shell=False,
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
            raise RuntimeError("azd environment operation failed; could not read or persist the account name.") from exc
    return result.stdout


def read_environment(executable, root):
    try:
        values = json.loads(azd(executable, root, ["env", "get-values", "--output", "json"]))
    except json.JSONDecodeError as exc:
        raise ValueError("azd environment output is not valid JSON.") from exc
    if not isinstance(values, dict):
        raise ValueError("azd environment output must be an object.")
    environment = values.get("AZURE_ENV_NAME")
    if not isinstance(environment, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", environment):
        raise ValueError("Invalid environment name. Select an environment using lowercase letters/digits/hyphens.")
    if ("AZURE_RESOURCE_GROUP" in values
            and values["AZURE_RESOURCE_GROUP"] != f"rg-reranker-{environment}"):
        raise ValueError("Existing resource group output does not match the selected environment.")
    return values


def prepare(project_root, regenerate_invalid=False):
    root = Path(project_root).resolve()
    executable = shutil.which("azd")
    if not executable:
        raise RuntimeError("azd is required on PATH to persist the account name.")
    values = read_environment(executable, root)
    chosen = choose_name(values, regenerate_invalid)
    if values.get(NAME_KEY) == chosen:
        return chosen
    # Only one azd-owned key is changed. No shell interpolation or .azure file rewrite.
    azd(executable, root, ["env", "set", NAME_KEY, chosen,
                           "--environment", values["AZURE_ENV_NAME"]])
    saved = read_environment(executable, root)
    if saved.get(NAME_KEY) != chosen or saved["AZURE_ENV_NAME"] != values["AZURE_ENV_NAME"]:
        raise RuntimeError("Could not verify persisted account name. Do not provision until state is resolved.")
    return chosen


def bootstrap(project_root, regenerate_invalid=False):
    """Local naming only. Never interpret unavailable first-use target flags."""
    chosen = prepare(project_root, regenerate_invalid)
    root = Path(project_root).resolve()
    executable = shutil.which("azd")
    if not executable:
        raise RuntimeError("azd is required on PATH.")
    values = read_environment(executable, root)
    # Reset even a previously authorized true. Only this run's authenticated
    # preprovision GET may authorize creation. This value is not an existence claim.
    azd(executable, root, ["env", "set", "AZURE_CREATE_INFERENCE", "false",
                          "--environment", values["AZURE_ENV_NAME"]])
    saved = read_environment(executable, root)
    if (saved.get("AZURE_CREATE_INFERENCE") != "false" or saved.get(NAME_KEY) != chosen
            or saved["AZURE_ENV_NAME"] != values["AZURE_ENV_NAME"]):
        raise RuntimeError("Could not verify fail-closed bootstrap state.")
    return chosen


def prepare_inference(project_root):
    root = Path(project_root).resolve()
    executable = shutil.which("azd")
    if not executable:
        raise RuntimeError("azd is required on PATH.")
    values = read_environment(executable, root)
    name = values.get(NAME_KEY)
    if not valid_name(name):
        raise ValueError("Persist a valid account UUID before checking inference.")
    try:
        subscription = str(uuid.UUID(values["AZURE_SUBSCRIPTION_ID"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("AZURE_SUBSCRIPTION_ID must be a UUID.") from exc
    location = values.get("AZURE_LOCATION")
    if location not in ("uksouth", "eastus2", "westus3"):
        raise ValueError("Select a supported AZURE_LOCATION before provisioning.")
    group = f"rg-reranker-{values['AZURE_ENV_NAME']}"
    resource_id = (f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
                   f"Microsoft.InferenceService/inferenceAccounts/{name}")
    with AzureCliCredential() as credential:
        token = credential.get_token("https://management.azure.com/.default").token
        response = requests.get(
            f"https://management.azure.com{resource_id}?api-version=2026-10-15",
            headers={"Authorization": f"Bearer {token}"}, timeout=30,
        )
    if response.status_code == 404:
        create = "true"
    elif response.status_code == 200:
        account = response.json()
        properties = account.get("properties", {})
        if (account.get("id", "").lower() != resource_id.lower()
                or account.get("location", "").replace(" ", "").lower() != location
                or properties.get("provisioningState") != "Succeeded"
                or properties.get("enableKeyBasedAuthentication") is not False):
            raise ValueError("Existing inference account is incompatible or not ready; inspect it without overwriting.")
        create = "false"
    else:
        raise RuntimeError(f"Inference preflight returned HTTP {response.status_code}. "
                           "Check Azure CLI identity, permissions and network; no create fallback.")
    azd(executable, root, ["env", "set", "AZURE_CREATE_INFERENCE", create,
                          "--environment", values["AZURE_ENV_NAME"]])
    if read_environment(executable, root).get("AZURE_CREATE_INFERENCE") != create:
        raise RuntimeError("Could not verify inference creation flag.")
    return create


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--regenerate-invalid-name", action="store_true",
                        help="Explicit recovery after a failed deployment; never replace a valid deployed name.")
    parser.add_argument("--bootstrap-only", action="store_true",
                        help="Preup: persist the name and disable creation without resolving a target or calling Azure.")
    args = parser.parse_args()
    try:
        bootstrap(args.project_root, args.regenerate_invalid_name)
        if not args.bootstrap_only:
            decision = prepare_inference(args.project_root)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
        logger.exception("Naming preflight failed.")
        print("Naming preflight failed. Check environment outputs, Azure CLI permissions "
              "and network access. No Azure resources were created by this helper.")
        return 1
    if args.bootstrap_only:
        print("Local bootstrap complete. UUID persisted/reused; inference creation disabled pending preprovision authorization.")
    else:
        print(f"Authenticated inference preflight complete. AZURE_CREATE_INFERENCE={decision}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
