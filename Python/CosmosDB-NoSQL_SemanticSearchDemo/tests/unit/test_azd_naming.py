"""Preprovision naming tests. No Azure or azd commands are executed."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import uuid
import sys
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("prepare_azd", ROOT / "scripts/prepare_azd.py")
naming = importlib.util.module_from_spec(spec)
spec.loader.exec_module(naming)

VALID = "a0000000-0000-4000-8000-000000000001"
OTHER = "b0000000-0000-4000-8000-000000000002"
NUMERIC = "10000000-0000-4000-8000-000000000001"
KEY = "AZURE_COSMOS_ACCOUNT_NAME"


@pytest.mark.parametrize("previous", [None, "true", "false"])
def test_bootstrap_resets_creation_without_subscription_or_credentials(tmp_path, monkeypatch, previous):
    store = {"AZURE_ENV_NAME": "offline-one", KEY: VALID}
    if previous is not None:
        store["AZURE_CREATE_INFERENCE"] = previous
    monkeypatch.setattr(naming, "prepare", lambda *args: VALID)
    monkeypatch.setattr(naming.shutil, "which", lambda _: "/mock/azd")
    monkeypatch.setattr(naming, "read_environment", lambda *args: dict(store))
    monkeypatch.setattr(naming, "AzureCliCredential", lambda: pytest.fail("Bootstrap must not authenticate"))
    monkeypatch.setattr(naming.requests, "get", lambda *args, **kwargs: pytest.fail("Bootstrap must not call Azure"))

    def persist(executable, root, args):
        assert args == ["env", "set", "AZURE_CREATE_INFERENCE", "false",
                        "--environment", "offline-one"]
        store["AZURE_CREATE_INFERENCE"] = args[3]

    monkeypatch.setattr(naming, "azd", persist)
    assert naming.bootstrap(tmp_path) == VALID
    assert store == {"AZURE_ENV_NAME": "offline-one", KEY: VALID,
                     "AZURE_CREATE_INFERENCE": "false"}


def test_bootstrap_cli_never_runs_authorization(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prepare_azd.py", "--project-root", str(tmp_path), "--bootstrap-only"])
    monkeypatch.setattr(naming, "bootstrap", lambda *args: VALID)
    monkeypatch.setattr(naming, "prepare_inference", lambda *args: pytest.fail("Authorization is preprovision-only"))
    assert naming.main() == 0


def test_default_cli_authorizes_only_after_reset(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["prepare_azd.py", "--project-root", str(tmp_path)])
    monkeypatch.setattr(naming, "bootstrap", lambda *args: calls.append("reset"))
    monkeypatch.setattr(naming, "prepare_inference", lambda *args: calls.append("get") or "true")
    assert naming.main() == 0
    assert calls == ["reset", "get"]


def test_bootstrap_must_verify_no_create_was_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(naming, "prepare", lambda *args: VALID)
    monkeypatch.setattr(naming.shutil, "which", lambda _: "/mock/azd")
    monkeypatch.setattr(naming, "read_environment", lambda *args: {
        "AZURE_ENV_NAME": "offline-one", KEY: VALID, "AZURE_CREATE_INFERENCE": "true"})
    monkeypatch.setattr(naming, "azd", lambda *args: None)
    with pytest.raises(RuntimeError, match="fail-closed bootstrap"):
        naming.bootstrap(tmp_path)

def test_generation_retries_numeric_leading_whole_uuids(monkeypatch):
    candidates = iter([uuid.UUID(NUMERIC), uuid.UUID(VALID)])
    monkeypatch.setattr(naming.uuid, "uuid4", lambda: next(candidates))
    assert naming.choose_name({}) == VALID
    with pytest.raises(StopIteration):
        next(candidates)


def test_generation_exhaustion_is_explicit(monkeypatch):
    calls = []

    def numeric():
        calls.append(1)
        return uuid.UUID(NUMERIC)

    monkeypatch.setattr(naming.uuid, "uuid4", numeric)
    with pytest.raises(RuntimeError, match="128"):
        naming.choose_name({})
    assert len(calls) == 128


@pytest.mark.parametrize("values", [
    {KEY: VALID},
    {"COSMOS_ACCOUNT_NAME": VALID},
    {KEY: VALID, "COSMOS_ACCOUNT_NAME": VALID, "INFERENCE_ACCOUNT_NAME": VALID},
    {KEY: VALID, "COSMOS_ACCOUNT_NAME": NUMERIC},
])
def test_valid_persisted_or_existing_output_is_reused(values, monkeypatch):
    def forbidden():
        pytest.fail("Existing valid account must not be regenerated")
    monkeypatch.setattr(naming.uuid, "uuid4", forbidden)
    assert naming.choose_name(values) == VALID
    assert naming.choose_name(values, regenerate_invalid=True) == VALID


def test_existing_bicep_uuid5_output_is_adopted_without_rewriting(monkeypatch):
    existing = "a0000000-0000-5000-8000-000000000003"
    monkeypatch.setattr(naming.uuid, "uuid4", lambda: pytest.fail("Must adopt existing UUID"))
    assert naming.choose_name({"COSMOS_ACCOUNT_NAME": existing}) == existing


@pytest.mark.parametrize("invalid", [NUMERIC, "freeform", VALID.upper(), "", 123])
@pytest.mark.parametrize("key", [KEY, "COSMOS_ACCOUNT_NAME"])
def test_invalid_existing_names_fail_without_explicit_authorization(invalid, key):
    with pytest.raises(ValueError, match="invalid"):
        naming.choose_name({key: invalid})


def test_explicit_regeneration_replaces_only_invalid_failed_name(monkeypatch):
    monkeypatch.setattr(naming.uuid, "uuid4", lambda: uuid.UUID(OTHER))
    assert naming.choose_name({KEY: NUMERIC, "COSMOS_ACCOUNT_NAME": NUMERIC},
                              regenerate_invalid=True) == OTHER
    # A valid old deployment takes precedence even during recovery.
    assert naming.choose_name({KEY: NUMERIC, "COSMOS_ACCOUNT_NAME": VALID},
                              regenerate_invalid=True) == VALID


def test_conflicting_valid_output_is_not_renamed():
    with pytest.raises(ValueError, match="conflict"):
        naming.choose_name({KEY: OTHER, "COSMOS_ACCOUNT_NAME": VALID})
    with pytest.raises(ValueError, match="conflict"):
        naming.choose_name({"COSMOS_ACCOUNT_NAME": VALID, "INFERENCE_ACCOUNT_NAME": OTHER})


def test_persist_before_provision_and_preserve_metadata(tmp_path, monkeypatch):
    store = {"AZURE_ENV_NAME": "offline-one", "AZURE_LOCATION": "uksouth",
             "COSMOS_ACCOUNT_NAME": VALID, "UNRELATED": "keep ' $() metadata"}
    calls = []
    monkeypatch.setattr(naming.shutil, "which", lambda _: "/mock/azd")

    def run(args, **kwargs):
        calls.append(args)
        assert kwargs["cwd"] == tmp_path
        assert kwargs["shell"] is False
        if args[1:3] == ["env", "set"]:
            assert args == ["/mock/azd", "env", "set", KEY, VALID,
                            "--environment", "offline-one"]
            store[KEY] = args[4]
            return SimpleNamespace(returncode=0, stdout="")
        assert args == ["/mock/azd", "env", "get-values", "--output", "json"]
        return SimpleNamespace(returncode=0, stdout=json.dumps(store))

    monkeypatch.setattr(naming.subprocess, "run", run)
    before = dict(store)
    assert naming.prepare(tmp_path) == VALID
    assert store == {**before, KEY: VALID}
    assert naming.prepare(tmp_path) == VALID
    assert sum(args[1:3] == ["env", "set"] for args in calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_failed_persistence_fails_before_arm(tmp_path, monkeypatch):
    monkeypatch.setattr(naming.shutil, "which", lambda _: "/mock/azd")
    monkeypatch.setattr(naming.uuid, "uuid4", lambda: uuid.UUID(VALID))

    def run(args, **kwargs):
        if args[1:3] == ["env", "set"]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout='{"AZURE_ENV_NAME":"offline-one"}')

    monkeypatch.setattr(naming.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="persist"):
        naming.prepare(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_write_must_be_visible_before_return(tmp_path, monkeypatch):
    monkeypatch.setattr(naming.shutil, "which", lambda _: "/mock/azd")
    monkeypatch.setattr(naming.uuid, "uuid4", lambda: uuid.UUID(VALID))
    monkeypatch.setattr(naming.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='{"AZURE_ENV_NAME":"offline-one"}'))
    with pytest.raises(RuntimeError, match="persist"):
        naming.prepare(tmp_path)


def test_invalid_environment_cannot_become_shell_code(tmp_path, monkeypatch):
    monkeypatch.setattr(naming.shutil, "which", lambda _: "/mock/azd")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "AZURE_ENV_NAME": "x; Write-Error bad", KEY: VALID}))

    monkeypatch.setattr(naming.subprocess, "run", run)
    with pytest.raises(ValueError, match="environment"):
        naming.prepare(tmp_path)
    assert len(calls) == 1


def test_preprovision_and_bicep_contract():
    yaml = (ROOT / "azure.yaml").read_text()
    assert "preprovision:" in yaml and "./scripts/preprovision.ps1" in yaml
    params = json.loads((ROOT / "infra/azd/main.parameters.json").read_text())
    assert params["parameters"]["cosmosAccountName"]["value"] == "${AZURE_COSMOS_ACCOUNT_NAME}"
    assert params["parameters"]["createInference"]["value"] == "${AZURE_CREATE_INFERENCE=false}"
    resources = (ROOT / "infra/azd/resources.bicep").read_text()
    assert "param cosmosAccountName string" in resources
    assert "guid(resourceGroup().id" not in resources
    assert "newGuid(" not in resources
    assert resources.count("name: cosmosAccountName") == 2
    assert "existing =" in resources
    assert "if (createInference == 'true')" in resources
    assert "createInference == 'true' ? newInference!.outputs.endpoint : inference.properties.endpoint" in resources


@pytest.mark.parametrize("missing", ["AZURE_SUBSCRIPTION_ID", "AZURE_LOCATION"])
def test_inference_preflight_requires_azd_resolved_selection(tmp_path, monkeypatch, missing):
    values = {"AZURE_ENV_NAME": "offline-one", "AZURE_SUBSCRIPTION_ID": VALID,
              "AZURE_LOCATION": "uksouth", KEY: VALID}
    values.pop(missing)
    monkeypatch.setattr(naming.shutil, "which", lambda _: "/mock/azd")
    monkeypatch.setattr(naming, "read_environment", lambda *args: dict(values))
    monkeypatch.setattr(naming, "AzureCliCredential",
                        lambda: pytest.fail("Do not authenticate against an unresolved target"))
    monkeypatch.setattr(naming, "azd",
                        lambda *args: pytest.fail("Do not persist a guessed subscription or inference decision"))
    with pytest.raises(ValueError, match=missing):
        naming.prepare_inference(tmp_path)


@pytest.mark.parametrize("status, expected", [(200, "false"), (404, "true")])
def test_inference_preflight_rechecks_live_state(tmp_path, monkeypatch, status, expected):
    store = {"AZURE_ENV_NAME": "offline-one", "AZURE_SUBSCRIPTION_ID": VALID,
             "AZURE_LOCATION": "uksouth", KEY: VALID, "AZURE_CREATE_INFERENCE": "stale"}
    resource_id = (f"/subscriptions/{VALID}/resourceGroups/rg-reranker-offline-one/"
                   f"providers/Microsoft.InferenceService/inferenceAccounts/{VALID}")
    monkeypatch.setattr(naming.shutil, "which", lambda _: "/mock/azd")
    monkeypatch.setattr(naming, "read_environment", lambda *args: dict(store))

    class Credential:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get_token(self, scope):
            assert scope == "https://management.azure.com/.default"
            return SimpleNamespace(token="offline-token")

    monkeypatch.setattr(naming, "AzureCliCredential", Credential)

    def get(url, **kwargs):
        assert url.startswith("https://management.azure.com" + resource_id)
        assert kwargs["timeout"] == 30
        return SimpleNamespace(status_code=status, json=lambda: {
            "id": resource_id, "location": "uksouth",
            "properties": {"provisioningState": "Succeeded", "enableKeyBasedAuthentication": False}})

    monkeypatch.setattr(naming.requests, "get", get)

    def set_flag(executable, root, args):
        assert args == ["env", "set", "AZURE_CREATE_INFERENCE", expected,
                        "--environment", "offline-one"]
        store["AZURE_CREATE_INFERENCE"] = args[3]

    monkeypatch.setattr(naming, "azd", set_flag)
    assert naming.prepare_inference(tmp_path) == expected


@pytest.mark.parametrize("status", [401, 403, 409, 429, 500])
def test_inference_preflight_never_creates_on_error(tmp_path, monkeypatch, status):
    monkeypatch.setattr(naming.shutil, "which", lambda _: "/mock/azd")
    monkeypatch.setattr(naming, "read_environment", lambda *args: {
        "AZURE_ENV_NAME": "offline-one", "AZURE_SUBSCRIPTION_ID": VALID,
        "AZURE_LOCATION": "uksouth", KEY: VALID})

    class Credential:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get_token(self, scope):
            return SimpleNamespace(token="offline-token")

    monkeypatch.setattr(naming, "AzureCliCredential", Credential)
    monkeypatch.setattr(naming.requests, "get", lambda *args, **kwargs: SimpleNamespace(status_code=status))
    monkeypatch.setattr(naming, "azd", lambda *args: pytest.fail("Must not change state on an ARM error"))
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        naming.prepare_inference(tmp_path)
