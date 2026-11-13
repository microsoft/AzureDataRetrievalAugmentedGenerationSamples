"""Offline azd contracts. ARM/live idempotence is an explicit operator gate."""

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
import uuid

from dotenv import dotenv_values
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("configure_azd", ROOT / "scripts/configure_azd.py")
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


def outputs(environment="offline-one"):
    # Synthetic letter-leading UUIDs, unrelated to any deployed account.
    account = ("a0000000-0000-4000-8000-000000000001" if environment == "offline-one"
               else "b0000000-0000-4000-8000-000000000002")
    subscription = str(uuid.UUID(int=1))
    group = f"rg-reranker-{environment}"
    scope = f"/subscriptions/{subscription}/resourceGroups/{group}/providers"
    return {
        "AZURE_ENV_NAME": environment,
        "AZURE_SUBSCRIPTION_ID": subscription,
        "AZURE_RESOURCE_GROUP": group,
        "COSMOS_ACCOUNT_NAME": account,
        "COSMOS_ACCOUNT_ID": f"{scope}/Microsoft.DocumentDB/databaseAccounts/{account}",
        "INFERENCE_ACCOUNT_NAME": account,
        "INFERENCE_ACCOUNT_ID": f"{scope}/Microsoft.InferenceService/inferenceAccounts/{account}",
        "COSMOS_URI": f"https://{account}.documents.azure.com:443/",
        "COSMOS_DB_DATABASE": "reranker",
        "AZURE_AI_INFERENCE_ENDPOINT": "https://offline.example.test/",
        "AZURE_OPENAI_ENDPOINT": f"https://aoai-{account}.openai.azure.com/",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "text-embedding-3-small",
        "AZURE_OPENAI_EMBEDDING_MODEL": "text-embedding-3-small",
        "AZURE_OPENAI_EMBEDDING_VERSION": "1",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
        "COSMOS_DB_CONTAINER_QFLAT": "reranker_dotnet_qflat",
        "COSMOS_DB_CONTAINER_DISKANN": "reranker_dotnet_diskann",
    }


def test_mocked_azd_command_and_config(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(config.shutil, "which", lambda name: "/mock/azd")

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(outputs()))

    monkeypatch.setattr(config.subprocess, "run", run)
    before = dict(os.environ)
    config.configure(tmp_path)
    args, kwargs = calls[0]
    assert args == ["/mock/azd", "env", "get-values", "--output", "json"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs.get("shell", False) is False
    assert dict(os.environ) == before
    values = dotenv_values(tmp_path / ".env")
    assert values["COSMOS_URI"] == outputs()["COSMOS_URI"]
    assert values["COSMOS_DB_DATABASE"] == "reranker"
    assert values["AZURE_AI_INFERENCE_ENDPOINT"] == outputs()["AZURE_AI_INFERENCE_ENDPOINT"]
    assert values["AZURE_OPENAI_ENDPOINT"] == outputs()["AZURE_OPENAI_ENDPOINT"]
    assert values["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"] == "text-embedding-3-small"
    script = (tmp_path / ".local/azd-env.ps1").read_text()
    assert "$env:COSMOS_URI =" in script
    assert "SetEnvironmentVariable" not in script
    assert "setx" not in script.lower()


def test_preserves_unrelated_multiline_values_and_switches(tmp_path):
    original = '# keep\nAZURE_OPENAI_API_KEY="a secret"\nOTHER="first\nCOSMOS_URI=not-a-binding\nlast"\n'
    (tmp_path / ".env").write_text(original + 'export COSMOS_URI="old"\nCOSMOS_URI=duplicate\n')
    config.configure(tmp_path, values=outputs())
    first = (tmp_path / ".env").read_bytes()
    config.configure(tmp_path, values=outputs())
    assert (tmp_path / ".env").read_bytes() == first
    config.configure(tmp_path, values=outputs("offline-two"))
    text = (tmp_path / ".env").read_text()
    assert text.startswith(original)
    parsed = dotenv_values(tmp_path / ".env")
    assert parsed["AZURE_OPENAI_API_KEY"] == "a secret"
    assert parsed["AZURE_OPENAI_AUTH_MODE"] == "entra"
    assert parsed["COSMOS_URI"] == outputs("offline-two")["COSMOS_URI"]
    assert outputs()["COSMOS_URI"] not in text
    assert "offline-two" in (tmp_path / ".local/azd-env.ps1").read_text()


def test_root_configures_both_languages(tmp_path):
    (tmp_path / "python").mkdir()
    (tmp_path / "python/.env").write_text("OPENAI_CUSTOM=keep\n")
    config.configure(tmp_path, include_dotnet=True, values=outputs())
    assert not (tmp_path / ".env").exists()
    assert dotenv_values(tmp_path / "python/.env")["OPENAI_CUSTOM"] == "keep"
    script = (tmp_path / ".local/azd-env.ps1").read_text()
    for name in ("COSMOS_DB_ENDPOINT", "COSMOS_URI", "INFERENCE_ENDPOINT",
                 "AZURE_AI_INFERENCE_ENDPOINT", "COSMOS_DB_DATABASE",
                 "COSMOS_DB_CONTAINER_QFLAT", "COSMOS_DB_CONTAINER_DISKANN"):
        assert f"$env:{name} =" in script
    assert (tmp_path / "python/.local/azd-env.ps1").exists()


@pytest.mark.parametrize("key", list(outputs()))
def test_missing_outputs_fail_without_changes(tmp_path, key):
    values = outputs()
    del values[key]
    (tmp_path / "python").mkdir()
    env_file = tmp_path / "python/.env"
    env_file.write_bytes(b"KEEP=original\r\n")
    with pytest.raises(ValueError, match="output"):
        config.configure(tmp_path, include_dotnet=True, values=values)
    assert env_file.read_bytes() == b"KEEP=original\r\n"
    assert not (tmp_path / ".local/azd-env.ps1").exists()


@pytest.mark.parametrize("key,value", [
    ("COSMOS_ACCOUNT_NAME", "freeform"),
    ("COSMOS_ACCOUNT_NAME", "10000000-0000-4000-8000-000000000001"),
    ("AZURE_COSMOS_ACCOUNT_NAME", "b0000000-0000-4000-8000-000000000002"),
    ("COSMOS_ACCOUNT_NAME", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"),
    ("COSMOS_URI", "https://host/'; Write-Error hacked; '"),
    ("COSMOS_URI", "http://offline.example.test/"),
    ("AZURE_AI_INFERENCE_ENDPOINT", "https://user:password@host/"),
    ("COSMOS_DB_DATABASE", "reranker\nEVIL=value"),
    ("AZURE_RESOURCE_GROUP", "an-existing-group"),
    ("INFERENCE_ACCOUNT_ID", "/another/account"),
    ("AZURE_ENV_NAME", "../escape"),
    ("COSMOS_DB_CONTAINER_QFLAT", "other"),
    ("AZURE_OPENAI_ENDPOINT", "https://wrong-account.openai.azure.com/"),
    ("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "bad\nINJECT=value"),
])
def test_malformed_outputs_fail_before_writing(tmp_path, key, value):
    values = outputs()
    values[key] = value
    with pytest.raises(ValueError):
        config.configure(tmp_path, include_dotnet=True, values=values)
    assert list(tmp_path.iterdir()) == []


def test_quoting_is_literal():
    assert config.powershell_literal("it's $(not code)`") == "'it''s $(not code)`'"


def test_generated_script_runs_literally_in_powershell(tmp_path):
    executable = config.shutil.which("pwsh")
    if not executable:
        pytest.fail("PowerShell 7 is a required azd prerequisite.")
    script = tmp_path / "env.ps1"
    literal = "it's $(throw 'must not execute') ` $HOME"
    script.write_bytes(config.environment_script({"AZD_QUOTING_TEST": literal}))
    runner = tmp_path / "check.ps1"
    runner.write_text(
        ". (Join-Path $PSScriptRoot 'env.ps1')\n"
        "$env:AZD_QUOTING_TEST | ConvertTo-Json -Compress\n",
        encoding="utf-8",
    )
    result = config.subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-File", str(runner)],
        capture_output=True, text=True, timeout=30, check=True, shell=False,
    )
    assert json.loads(result.stdout) == literal
    assert "AZD_QUOTING_TEST" not in os.environ


def test_invalid_existing_dotenv_does_not_corrupt_any_config(tmp_path):
    config.configure(tmp_path, values=outputs())
    env_file = tmp_path / ".env"
    env_file.write_bytes(b'OTHER="unterminated\n')
    script = tmp_path / ".local/azd-env.ps1"
    before = script.read_bytes()
    with pytest.raises(ValueError, match="malformed"):
        config.configure(tmp_path, values=outputs("offline-two"))
    assert env_file.read_bytes() == b'OTHER="unterminated\n'
    assert script.read_bytes() == before


def test_sourceable_root_script_switches_both_apps(tmp_path):
    executable = config.shutil.which("pwsh")
    if not executable:
        pytest.fail("PowerShell 7 is a required azd prerequisite.")
    (tmp_path / "python").mkdir()
    config.configure(tmp_path, include_dotnet=True, values=outputs())
    first = tmp_path / "first.ps1"
    first.write_bytes((tmp_path / ".local/azd-env.ps1").read_bytes())
    config.configure(tmp_path, include_dotnet=True, values=outputs("offline-two"))
    runner = tmp_path / "check.ps1"
    runner.write_text(
        ". (Join-Path $PSScriptRoot 'first.ps1')\n"
        "$first = $env:COSMOS_URI\n"
        ". (Join-Path $PSScriptRoot '.local/azd-env.ps1')\n"
        "@{first=$first; python=$env:COSMOS_URI; dotnet=$env:COSMOS_DB_ENDPOINT;"
        "inference=$env:INFERENCE_ENDPOINT; qflat=$env:COSMOS_DB_CONTAINER_QFLAT;"
        "environment=$env:AZURE_ENV_NAME} | ConvertTo-Json -Compress\n",
        encoding="utf-8",
    )
    result = config.subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-File", str(runner)],
        capture_output=True, text=True, timeout=30, check=True, shell=False,
    )
    actual = json.loads(result.stdout)
    assert actual["first"] == outputs()["COSMOS_URI"]
    assert actual["python"] == actual["dotnet"] == outputs("offline-two")["COSMOS_URI"]
    assert actual["inference"] == outputs("offline-two")["AZURE_AI_INFERENCE_ENDPOINT"]
    assert actual["qflat"] == "reranker_dotnet_qflat"
    assert actual["environment"] == "offline-two"


def test_guid_shape_and_template_uses_persisted_name():
    resource = (ROOT / "infra/azd/resources.bicep").read_text()
    assert "param cosmosAccountName string" in resource
    assert "guid(resourceGroup().id" not in resource
    assert "newGuid(" not in resource and "utcNow(" not in resource
    for environment in ("offline-one", "offline-two"):
        validated = config.validate_outputs(outputs(environment), False)
        account = validated["COSMOS_ACCOUNT_NAME"]
        assert re.fullmatch(r"[a-f][0-9a-f]{7}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", account)
    assert outputs()["COSMOS_ACCOUNT_NAME"] == outputs()["COSMOS_ACCOUNT_NAME"]
    assert outputs()["COSMOS_ACCOUNT_NAME"] != outputs("offline-two")["COSMOS_ACCOUNT_NAME"]


def test_azd_failure_or_invalid_json_is_not_absence(tmp_path, monkeypatch):
    monkeypatch.setattr(config.shutil, "which", lambda name: "/mock/azd")
    for result in (subprocess.CompletedProcess(["mock-azd"], 1, stdout="", stderr=""),
                   SimpleNamespace(returncode=0, stdout="not json")):
        monkeypatch.setattr(config.subprocess, "run", lambda *a, **k: result)
        with pytest.raises((ValueError, RuntimeError)):
            config.configure(tmp_path)
        assert list(tmp_path.iterdir()) == []


def test_replace_failure_rolls_back_all_files(tmp_path, monkeypatch):
    config.configure(tmp_path, values=outputs())
    targets = [tmp_path / ".env", tmp_path / ".local/azd-env.ps1"]
    before = {p: p.read_bytes() for p in targets}
    replace = config.os.replace
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated disk failure")
        return replace(source, target)

    monkeypatch.setattr(config.os, "replace", fail_second)
    with pytest.raises(OSError):
        config.configure(tmp_path, values=outputs("offline-two"))
    assert {p: p.read_bytes() for p in targets} == before


def test_iac_contract():
    resources = (ROOT / "infra/azd/resources.bicep").read_text()
    main = (ROOT / "infra/azd/main.bicep").read_text()
    params = json.loads((ROOT / "infra/azd/main.parameters.json").read_text())
    assert "param cosmosAccountName string" in resources
    assert "guid(resourceGroup().id" not in resources
    assert "utcNow(" not in resources and "newGuid(" not in resources
    for token in (
        "Microsoft.DocumentDB/databaseAccounts@2025-05-01-preview",
        "Microsoft.InferenceService/inferenceAccounts@2026-10-15",
        "EnableNoSQLVectorSearch", "EnableNoSQLFullTextSearchPreviewFeatures",
        "disableLocalAuth: true", "throughput: 400", "dimensions: 1536",
        "distanceFunction: 'cosine'", "dataType: 'float32'", "'/id'",
        "'/embedding'", "'/text'", "'en-US'", "'quantizedFlat'", "'diskANN'",
        "'search_qflat'", "'search_diskann'", "'reranker_dotnet_qflat'",
        "'reranker_dotnet_diskann'", "00000000-0000-0000-0000-000000000002",
        "6c74a7c5-4a87-40f9-bb03-61e49aecbc78", "scope: cosmos.id",
        "scope: inference", "inference.properties.endpoint",
    ):
        assert token in resources
    assert "targetScope = 'subscription'" in main
    assert "'rg-reranker-${environmentName}'" in main
    assert params["parameters"]["principalId"]["value"] == "${AZURE_PRINCIPAL_ID}"
    assert "services:" not in (ROOT / "azure.yaml").read_text()
    assert "10000" not in resources and "Microsoft.Web" not in resources
    target_root = ROOT.parent
    if (target_root / "dotnet").is_dir():
        root_main = (target_root / "infra/azd/main.bicep").read_text()
        assert "includeDotnet: true" in root_main
        assert "../../python/infra/azd/resources.bicep" in root_main
        assert "services:" not in (target_root / "azure.yaml").read_text()
