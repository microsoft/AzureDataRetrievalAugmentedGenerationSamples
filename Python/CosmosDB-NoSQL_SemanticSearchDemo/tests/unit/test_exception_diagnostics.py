"""Offline exception identity and private-terminal/public-output boundaries."""

import importlib.util
import json
import logging
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

import cleanup
import container_setup
import inference_setup
import load_data

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = "https://private.invalid/?key=secret query=document-content"


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_private_log(caplog, original):
    records = [record for record in caplog.records if record.exc_info]
    assert len(records) == 1
    assert records[0].exc_info[1] is original
    assert records[0].exc_info[2] is not None
    assert PRIVATE in logging.Formatter().format(records[0])


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
@pytest.mark.parametrize("boundary", ["load", "setup", "inference", "cleanup",
                                    "configure", "prepare"])
def test_cli_failure_logs_original_once_and_prints_safe_failure(
        monkeypatch, capsys, caplog, boundary, error_type):
    original = error_type(PRIVATE)
    failure = Mock(side_effect=original)
    args = ["--subscription", "sub", "--resource-group", "rg", "--account", "account"]
    if boundary == "load":
        module = load_data
        monkeypatch.setattr(module, "read_json", failure)
        args = ["--path_to_json_array", "unused.json", "--max-items", "1", "--confirm-write"]
    elif boundary == "setup":
        module = container_setup
        monkeypatch.setattr(module, "setup_containers", failure)
        args += ["--database", "db"]
    elif boundary == "inference":
        module = inference_setup
        monkeypatch.setattr(module, "initialize", failure)
        args += ["--location", "uksouth"]
    elif boundary == "cleanup":
        module = cleanup
        monkeypatch.setattr(module, "az_json", failure)
        args += ["--database", "db", "--container", "search_qflat",
                 "--confirm-delete", "account/db/search_qflat"]
    else:
        module = script(f"{boundary}_azd")
        monkeypatch.setattr(module, "configure" if boundary == "configure" else "bootstrap", failure)
        monkeypatch.setattr(sys, "argv", [f"{boundary}_azd.py"])
    with caplog.at_level(logging.ERROR):
        code = module.main() if boundary in ("configure", "prepare") else module.main(args)
    assert code == 1
    failure.assert_called_once()
    output = capsys.readouterr().out
    assert PRIVATE not in output and "secret" not in output
    assert output.strip()
    assert_private_log(caplog, original)


def test_loader_worker_keeps_original_traceback_and_sanitized_counts(monkeypatch, caplog):
    original = ValueError(PRIVATE)
    failure = Mock(side_effect=original)
    monkeypatch.setattr(load_data, "upsert_with_retry", failure)
    failures = []
    with caplog.at_level(logging.ERROR):
        counts = load_data.load_items({"offline": Mock()}, [{"id": "test"}], failures=failures)
    assert counts == {"offline": {"attempted": 1, "succeeded": 0, "failed": 1}}
    assert failures[0]["exception_type"] == "ValueError"
    assert PRIVATE not in json.dumps(failures)
    failure.assert_called_once()
    assert_private_log(caplog, original)


@pytest.mark.parametrize("name", ["configure_azd", "prepare_azd"])
def test_json_wrapper_preserves_original_cause(monkeypatch, name):
    module = script(name)
    original = json.JSONDecodeError("Invalid private input", PRIVATE, 0)
    monkeypatch.setattr(module.json, "loads", Mock(side_effect=original))
    if name == "configure_azd":
        monkeypatch.setattr(module.shutil, "which", lambda _: "mock-azd")
        monkeypatch.setattr(module.subprocess, "run", Mock(return_value=Mock(returncode=0, stdout="{}")))
        call = lambda: module.read_outputs(ROOT)
    else:
        monkeypatch.setattr(module, "azd", Mock(return_value="{}"))
        call = lambda: module.read_environment("mock-azd", ROOT)
    with pytest.raises(ValueError) as caught:
        call()
    assert caught.value.__cause__ is original
    assert original.__traceback__ is not None
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("name", ["configure_azd", "prepare_azd"])
def test_uuid_wrapper_preserves_original_cause(monkeypatch, name):
    module = script(name)
    original = ValueError(PRIVATE)
    monkeypatch.setattr(module.uuid, "UUID", Mock(side_effect=original))
    if name == "configure_azd":
        # Valid shape reaches UUID validation, without resolving any resource.
        values = {key: "offline" for key in module.PYTHON_KEYS}
        values.update(AZURE_ENV_NAME="offline", AZURE_RESOURCE_GROUP="rg-reranker-offline",
                      AZURE_SUBSCRIPTION_ID="offline", COSMOS_ACCOUNT_NAME="offline",
                      COSMOS_ACCOUNT_ID="offline", INFERENCE_ACCOUNT_NAME="offline",
                      INFERENCE_ACCOUNT_ID="offline")
        call = lambda: module.validate_outputs(values, False)
    else:
        monkeypatch.setattr(module.shutil, "which", lambda _: "mock-azd")
        monkeypatch.setattr(module, "read_environment", lambda *args: {
            module.NAME_KEY: "a0000000-0000-4000-8000-000000000001",
            "AZURE_SUBSCRIPTION_ID": "offline"})
        call = lambda: module.prepare_inference(ROOT)
    with pytest.raises(ValueError) as caught:
        call()
    assert caught.value.__cause__ is original
    assert original.__traceback__ is not None
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("name", ["container_setup", "configure_azd", "prepare_azd"])
def test_cli_wrapper_retains_exit_code_command_and_captured_output(monkeypatch, name):
    module = container_setup if name == "container_setup" else script(name)
    monkeypatch.setattr(module.shutil, "which", lambda _: "mock-cli")
    result = subprocess.CompletedProcess(["mock-cli", "offline"], 7,
                                         stdout=PRIVATE, stderr="private SDK diagnostic")
    run = Mock(return_value=result)
    monkeypatch.setattr(module.subprocess, "run", run)
    if name == "container_setup":
        call = lambda: module.az_json("offline")
    elif name == "configure_azd":
        call = lambda: module.read_outputs(ROOT)
    else:
        call = lambda: module.azd("mock-cli", ROOT, ["offline"])
    with pytest.raises(RuntimeError) as caught:
        call()
    cause = caught.value.__cause__
    assert isinstance(cause, subprocess.CalledProcessError)
    assert cause.returncode == 7 and cause.cmd == result.args
    assert cause.stdout == PRIVATE and cause.stderr == result.stderr
    assert cause.__traceback__ is not None
    assert PRIVATE not in str(caught.value)
    run.assert_called_once()


@pytest.mark.parametrize("name", ["configure_azd", "prepare_azd"])
@pytest.mark.parametrize("stdout,stderr", [
    ("private-stdout-detail", "private-stderr-detail"),
    ("private-shared-detail", "private-shared-detail"),
    ("\nprivate-shared-detail\n", "private-shared-detail"),
    ("", "private-stderr-detail"),
    ("private-stdout-detail", None),
    (" \n", None),
])
def test_failed_azd_output_reaches_private_terminal_once_with_traceback(
        monkeypatch, capsys, caplog, name, stdout, stderr):
    module = script(name)
    result = subprocess.CompletedProcess(["mock-azd", "offline"], 7,
                                         stdout=stdout, stderr=stderr)
    run = Mock(return_value=result)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.shutil, "which", lambda _: "mock-azd")
    monkeypatch.setattr(sys, "argv", [f"{name}.py"])
    # Exercise actual terminal formatting, not only LogRecord/cause attributes.
    handler = logging.StreamHandler()
    module.logger.addHandler(handler)
    try:
        with caplog.at_level(logging.ERROR):
            assert module.main() == 1
    finally:
        module.logger.removeHandler(handler)
    run.assert_called_once()
    terminal = capsys.readouterr()
    details = {value.strip() for value in (stdout, stderr) if value and value.strip()}
    for detail in details:
        assert terminal.err.count(detail) == 1
        assert detail not in terminal.out
    records = [record for record in caplog.records if record.name == name]
    detail_records = [record for record in records if not record.exc_info]
    assert len(detail_records) == len(details)
    assert all("Sensitive local azd" in record.getMessage() for record in detail_records)
    assert all("do not share raw logs" in record.getMessage() for record in detail_records)
    if stderr and stderr.strip():
        assert "stderr" in detail_records[0].getMessage()
    if stdout and stdout.strip() and stdout.strip() != (stderr or "").strip():
        assert "stdout" in detail_records[-1].getMessage()
    tracebacks = [record for record in records if record.exc_info]
    assert len(tracebacks) == 1
    cause = tracebacks[0].exc_info[1].__cause__
    assert isinstance(cause, subprocess.CalledProcessError)
    assert cause.stdout == stdout and cause.stderr == stderr
    assert cause.returncode == 7 and cause.__traceback__ is not None
    assert "Traceback (most recent call last)" in terminal.err
    assert "CalledProcessError" in terminal.err and "RuntimeError" in terminal.err
    assert "direct cause" in terminal.err
    assert terminal.out.strip()  # The existing safe failure summary is retained.


@pytest.mark.parametrize("name", ["configure_azd", "prepare_azd"])
def test_successful_azd_output_is_not_logged(monkeypatch, caplog, capsys, name):
    module = script(name)
    values = {"AZURE_ENV_NAME": "offline", "PRIVATE_SETTING": "must-not-be-logged"}
    stdout = json.dumps(values)
    run = Mock(return_value=subprocess.CompletedProcess(
        ["mock-azd", "offline"], 0, stdout=stdout, stderr="successful-command-warning"))
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.shutil, "which", lambda _: "mock-azd")
    with caplog.at_level(logging.DEBUG):
        if name == "configure_azd":
            assert module.read_outputs(ROOT) == values
        else:
            assert module.azd("mock-azd", ROOT, ["env", "get-values"]) == stdout
    run.assert_called_once()
    assert not caplog.records
    terminal = capsys.readouterr()
    assert not terminal.out and not terminal.err
