from unittest.mock import Mock

import pytest

from inference_setup import API_VERSION, ROLE_ID, initialize

COSMOS = {"id": "/subscriptions/sub/resourceGroups/rg/providers/"
                 "Microsoft.DocumentDB/databaseAccounts/account", "name": "account"}
RESOURCE = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.InferenceService/inferenceAccounts/account"
EXISTING = {
    "id": RESOURCE, "name": "account", "location": "uksouth",
    "properties": {"provisioningState": "Succeeded", "enableKeyBasedAuthentication": False,
                   "endpoint": "https://example-inference.dbinference.azure.com"},
}


def dependencies(response=EXISTING):
    arm = Mock()
    arm.get.return_value = response
    cli = Mock(return_value=COSMOS)
    return arm, cli


def test_reuse_reads_cosmos_and_exact_inference_only():
    arm, cli = dependencies()
    result = initialize("sub", "rg", "account", "uksouth", arm=arm, cli=cli)
    assert result["endpoint"] == EXISTING["properties"]["endpoint"]
    assert result["action"] == "reused"
    cli.assert_called_once_with("cosmosdb", "show", "--subscription", "sub",
                                "--resource-group", "rg", "--name", "account")
    arm.get.assert_called_once_with(RESOURCE, allow_missing=True)
    arm.put.assert_not_called()
    assert API_VERSION == "2026-10-15"


def test_missing_default_is_read_only():
    arm, cli = dependencies(None)
    result = initialize("sub", "rg", "account", "uksouth", arm=arm, cli=cli)
    assert result["action"] == "would-create"
    assert result["endpoint"] is None
    arm.put.assert_not_called()
    assert cli.call_count == 1


def test_creation_is_explicit_and_body_is_location_only():
    arm, cli = dependencies(None)
    arm.get.side_effect = [None, None, EXISTING]
    arm.put.return_value = EXISTING
    result = initialize("sub", "rg", "account", "uksouth", confirm_create=True,
                        arm=arm, cli=cli, sleep=Mock())
    arm.put.assert_called_once_with(RESOURCE, {"location": "uksouth"})
    assert result["endpoint"] == EXISTING["properties"]["endpoint"]
    assert result["action"] == "created"
    assert cli.call_count == 1


def test_resource_appearing_after_preflight_is_reused_without_put():
    arm, cli = dependencies()
    arm.get.side_effect = [None, EXISTING]
    result = initialize("sub", "rg", "account", "uksouth", confirm_create=True,
                        arm=arm, cli=cli)
    arm.put.assert_not_called()
    assert result["action"] == "reused"


@pytest.mark.parametrize("change", [
    {"location": "different-region"},
    {"properties": {**EXISTING["properties"], "enableKeyBasedAuthentication": True}},
    {"properties": {**EXISTING["properties"], "provisioningState": "Failed"}},
    {"properties": {**EXISTING["properties"], "endpoint": "http://insecure.example"}},
    {"properties": {**EXISTING["properties"], "endpoint": None}},
    {"name": "another-account"},
])
def test_incompatible_resource_is_never_overwritten(change):
    arm, cli = dependencies({**EXISTING, **change})
    with pytest.raises(ValueError):
        initialize("sub", "rg", "account", "uksouth", confirm_create=True, arm=arm, cli=cli)
    arm.put.assert_not_called()
    assert cli.call_count == 1


def test_auth_failure_is_not_absence():
    arm, cli = dependencies()
    arm.get.side_effect = RuntimeError("ARM GET failed (HTTP 403)")
    with pytest.raises(RuntimeError):
        initialize("sub", "rg", "account", "uksouth", confirm_create=True, arm=arm, cli=cli)
    arm.put.assert_not_called()


def test_explicit_role_assignment_uses_exact_inference_scope_and_current_user():
    arm, cli = dependencies()
    cli.side_effect = [COSMOS, {"id": "principal"}, [], {"id": "assignment"}]
    result = initialize("sub", "rg", "account", "uksouth", assign_role=True, arm=arm, cli=cli)
    calls = [call.args for call in cli.call_args_list]
    assert calls[1] == ("ad", "signed-in-user", "show")
    create = calls[-1]
    assert create[:3] == ("role", "assignment", "create")
    assert create[create.index("--role") + 1] == ROLE_ID
    assert create[create.index("--scope") + 1] == RESOURCE
    assert create[create.index("--assignee-object-id") + 1] == "principal"
    assert result["role"] == "assigned"
    arm.put.assert_not_called()


def test_existing_assignment_is_reused():
    arm, cli = dependencies()
    cli.side_effect = [COSMOS, [{
        "principalId": "principal", "scope": RESOURCE,
        "roleDefinitionId": f"/subscriptions/sub/providers/Microsoft.Authorization/roleDefinitions/{ROLE_ID}",
    }]]
    result = initialize("sub", "rg", "account", "uksouth", assign_role=True,
                        principal_id="principal", arm=arm, cli=cli)
    assert result["role"] == "reused"
    assert all(call.args[:3] != ("role", "assignment", "create") for call in cli.call_args_list)


def test_missing_resource_does_not_assign_role():
    arm, cli = dependencies(None)
    result = initialize("sub", "rg", "account", "uksouth", assign_role=True, arm=arm, cli=cli)
    assert result["action"] == "would-create"
    assert cli.call_count == 1


def test_provisioning_poll_is_bounded():
    arm, cli = dependencies()
    pending = {**EXISTING, "properties": {"provisioningState": "Creating"}}
    arm.get.side_effect = [None, None] + [pending] * 3
    arm.put.return_value = pending
    sleep = Mock()
    with pytest.raises(RuntimeError, match="did not finish"):
        initialize("sub", "rg", "account", "uksouth", confirm_create=True,
                   arm=arm, cli=cli, sleep=sleep, poll_attempts=3)
    assert arm.get.call_count == 5
    assert sleep.call_count == 2


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_transport_errors_never_become_missing(status):
    from inference_setup import ArmClient
    arm = ArmClient.__new__(ArmClient)
    arm.credential = Mock()
    arm.credential.get_token.return_value.token = "not-a-real-token"
    arm.session = Mock()
    arm.session.request.return_value.status_code = status
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        arm.get(RESOURCE, allow_missing=True)


def test_transport_404_is_the_only_missing_signal():
    from inference_setup import ArmClient
    arm = ArmClient.__new__(ArmClient)
    arm.credential, arm.session = Mock(), Mock()
    arm.credential.get_token.return_value.token = "not-a-real-token"
    arm.session.request.return_value.status_code = 404
    assert arm.get(RESOURCE, allow_missing=True) is None
    call = arm.session.request.call_args
    assert call.args[0] == "GET"
    assert call.args[1].endswith(RESOURCE + "?api-version=2026-10-15")
    assert call.kwargs["allow_redirects"] is False


def test_transport_creation_has_location_only_and_conditional_header():
    from inference_setup import ArmClient
    arm = ArmClient.__new__(ArmClient)
    arm.credential, arm.session = Mock(), Mock()
    arm.credential.get_token.return_value.token = "not-a-real-token"
    arm.session.request.return_value.status_code = 201
    arm.session.request.return_value.json.return_value = EXISTING
    assert arm.put(RESOURCE, {"location": "uksouth"}) == EXISTING
    call = arm.session.request.call_args
    assert call.kwargs["json"] == {"location": "uksouth"}
    assert call.kwargs["headers"]["If-None-Match"] == "*"
