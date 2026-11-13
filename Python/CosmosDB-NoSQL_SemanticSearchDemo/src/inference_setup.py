"""Explicit companion inference setup for an existing, same-named Cosmos account."""

import argparse
import json
import logging
import time
from urllib.parse import quote, urlsplit

from container_setup import az_json

API_VERSION = "2026-10-15"
ROLE_ID = "6c74a7c5-4a87-40f9-bb03-61e49aecbc78"
logger = logging.getLogger(__name__)


class ArmClient:
    """Azure CLI credential in memory; no tokens, keys or raw responses are printed."""

    def __init__(self):
        import requests
        from azure.identity import AzureCliCredential
        self.credential = AzureCliCredential()
        self.session = requests.Session()

    def request(self, method, resource_id, body=None, allow_missing=False):
        token = self.credential.get_token("https://management.azure.com/.default").token
        url = ("https://management.azure.com" + quote(resource_id, safe="/")
               + "?api-version=" + API_VERSION)
        headers = {"Authorization": "Bearer " + token}
        if method == "PUT":
            headers["If-None-Match"] = "*"
        response = self.session.request(method, url, headers=headers, json=body,
                                        timeout=(10, 60), allow_redirects=False)
        if response.status_code == 404 and allow_missing:
            return None
        if response.status_code not in (200, 201, 202):
            raise RuntimeError(f"ARM {method} failed (HTTP {response.status_code}). "
                               "Check provider registration, permissions, region and resource state.")
        return response.json() if response.content else {}

    def get(self, resource_id, allow_missing=False):
        return self.request("GET", resource_id, allow_missing=allow_missing)

    def put(self, resource_id, body):
        return self.request("PUT", resource_id, body=body)

    def close(self):
        self.session.close()
        self.credential.close()


def validate_resource(resource, resource_id, account, location):
    properties = resource.get("properties", {})
    endpoint = properties.get("endpoint")
    parsed = urlsplit(endpoint) if isinstance(endpoint, str) else None
    if (str(resource.get("id", "")).lower() != resource_id.lower()
            or resource.get("name") != account
            or str(resource.get("location", "")).lower().replace(" ", "")
            != location.lower().replace(" ", "")
            or properties.get("provisioningState") != "Succeeded"
            or properties.get("enableKeyBasedAuthentication") is not False
            or parsed is None or parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Existing inference resource is incompatible or not ready. "
                         "Check name, region, Succeeded state, keyless authentication and endpoint. "
                         "It will not be overwritten.")
    return endpoint


def initialize(subscription, resource_group, account, location, *, confirm_create=False,
               assign_role=False, principal_id=None, principal_type="ServicePrincipal",
               arm=None, cli=az_json, sleep=time.sleep, poll_attempts=30):
    if not 1 <= poll_attempts <= 60:
        raise ValueError("poll_attempts must be between 1 and 60.")
    for value in (subscription, resource_group, account, location):
        if not value or any(character in value for character in "/\\?#\r\n"):
            raise ValueError("Supply nonempty, single-segment resource identifiers and region.")
    # This command reads the existing Cosmos account only. No databaseAccounts PUT.
    cosmos = cli("cosmosdb", "show", "--subscription", subscription,
                 "--resource-group", resource_group, "--name", account)
    prefix = f"/subscriptions/{subscription}/resourceGroups/{resource_group}/providers/"
    cosmos_id = prefix + f"Microsoft.DocumentDB/databaseAccounts/{account}"
    if str(cosmos.get("id", "")).lower() != cosmos_id.lower():
        raise ValueError("Existing Cosmos account does not match the explicit subscription/group/name.")
    resource_id = prefix + f"Microsoft.InferenceService/inferenceAccounts/{account}"
    owns_arm = arm is None
    arm = arm or ArmClient()
    try:
        resource = arm.get(resource_id, allow_missing=True)
        action = "reused"
        if resource is None:
            if not confirm_create:
                return {"action": "would-create", "endpoint": None, "role": "not-requested",
                        "message": "Read-only inspection. Re-run with --confirm-create to provision inference."}
            # Recheck immediately before PUT. Never interpret 401/403/network errors as absence.
            resource = arm.get(resource_id, allow_missing=True)
            if resource is None:
                arm.put(resource_id, {"location": location})
                action = "created"
                for attempt in range(poll_attempts):
                    resource = arm.get(resource_id, allow_missing=True)
                    state = (resource or {}).get("properties", {}).get("provisioningState")
                    if state == "Succeeded":
                        break
                    if state in ("Failed", "Canceled"):
                        raise RuntimeError("Inference provisioning failed. Inspect resource state; no automatic retry PUT.")
                    if attempt < poll_attempts - 1:
                        sleep(5)
                else:
                    raise RuntimeError("Inference provisioning did not finish within the polling limit. "
                                       "Inspect/reuse later; no deletion or replacement was attempted.")
        endpoint = validate_resource(resource, resource_id, account, location)
        role = "not-requested"
        if assign_role:
            if not principal_id:
                principal_id = cli("ad", "signed-in-user", "show")["id"]
                principal_type = "User"
            if not principal_id or any(c in principal_id for c in "/\\?#\r\n"):
                raise ValueError("Supply a valid principal object ID.")
            assignments = cli("role", "assignment", "list", "--subscription", subscription,
                              "--scope", resource_id, "--all")
            present = any(
                str(entry.get("principalId", "")).lower() == principal_id.lower()
                and str(entry.get("scope", "")).lower() == resource_id.lower()
                and str(entry.get("roleDefinitionId", "")).lower().endswith("/" + ROLE_ID)
                for entry in assignments)
            if present:
                role = "reused"
            else:
                cli("role", "assignment", "create", "--subscription", subscription,
                    "--assignee-object-id", principal_id,
                    "--assignee-principal-type", principal_type,
                    "--role", ROLE_ID, "--scope", resource_id)
                role = "assigned"
        return {"action": action, "endpoint": endpoint, "role": role}
    finally:
        if owns_arm:
            arm.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("subscription", "resource-group", "account", "location"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--confirm-create", action="store_true",
                        help="Create only a missing companion account. No Cosmos changes.")
    parser.add_argument("--assign-role", action="store_true",
                        help="Explicitly grant/reuse Semantic Reranker User at inference scope.")
    parser.add_argument("--principal-id", help="Object ID. Default with --assign-role: signed-in user.")
    parser.add_argument("--principal-type", choices=["User", "Group", "ServicePrincipal"],
                        default="ServicePrincipal")
    args = parser.parse_args(argv)
    try:
        result = initialize(args.subscription, args.resource_group, args.account, args.location,
                            confirm_create=args.confirm_create, assign_role=args.assign_role,
                            principal_id=args.principal_id, principal_type=args.principal_type)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        from search_demo import error_details
        logger.exception("Inference setup failed.")
        print(json.dumps({"error": "Inference setup did not complete.",
                          "diagnostic": error_details(exc),
                          "hint": "Inspect explicit targets, Azure CLI authentication, "
                          "provider registration and network access."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
