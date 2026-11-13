from pathlib import Path
import shutil
import socket
import subprocess
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_bootstrap_and_authorization_have_separate_hook_phases():
    roots = [ROOT]
    if (ROOT.parent / "dotnet").is_dir():
        roots.append(ROOT.parent)
    for root in roots:
        yaml = (root / "azure.yaml").read_text()
        assert "workflows:\n  up:\n    steps:\n      - azd: provision\n" in yaml
        assert yaml.count("- azd:") == 1
        bootstrap = re.search(r"^  preup:\n(?P<body>(?:^    .*\n)+)", yaml, re.MULTILINE)
        assert bootstrap
        assert "run: ./scripts/preup.ps1" in bootstrap["body"]
        assert "continueOnError: false" in bootstrap["body"]
        assert "-BootstrapOnly" in (root / "scripts/preup.ps1").read_text()
        block = re.search(
            r"^  preprovision:\n(?P<body>(?:^    .*\n)+)", yaml, re.MULTILINE)
        assert block, f"{root.name}: missing preprovision preparation hook"
        assert "run: ./scripts/preprovision.ps1" in block["body"]
        assert "shell: pwsh" in block["body"]
        assert "continueOnError: false" in block["body"]
        runner = (root / "scripts/preprovision.ps1").read_text()
        assert "-Prepare" in runner
        assert "-BootstrapOnly" not in runner
    preparation = (ROOT / "scripts/postprovision.ps1").read_text()
    assert "bootstrap.ps1" in preparation and "prepare_azd.py" in preparation


def test_lifecycle_separates_configuration_and_seed():
    yaml = (ROOT / "azure.yaml").read_text()
    assert "postup:" in yaml and "./scripts/postup.ps1" in yaml
    assert "services:" not in yaml
    config = (ROOT / "scripts/postprovision.ps1").read_text()
    assert "seed_movies" not in config
    assert "bootstrap.ps1" in config
    seed = (ROOT / "scripts/postup.ps1").read_text()
    assert "--confirm-write" in seed and "seed_movies.py" in seed
    assert "--cleanup-original-fixtures" in seed
    launcher = (ROOT / "scripts/start.ps1").read_text()
    assert "seed_movies" not in launcher and "upsert" not in launcher
    assert ". $config" in launcher and "$child.Kill($true)" in launcher
    assert "Stop-Process" not in launcher and "Get-Process" not in launcher


def test_openai_infrastructure_is_keyless_pay_per_token():
    text = (ROOT / "infra/azd/embeddings.bicep").read_text()
    for required in ("disableLocalAuth: true", "customSubDomainName:",
                     "scope: account", "text-embedding-3-small", "GlobalStandard",
                     "param capacity int = 30"):
        assert required in text
    assert "Provisioned" not in text


def test_powershell_scripts_parse():
    executable = shutil.which("pwsh")
    assert executable, "PowerShell 7 is required."
    paths = [*ROOT.joinpath("scripts").glob("*.ps1")]
    if (ROOT.parent / "dotnet").is_dir():
        paths.extend(ROOT.parent.joinpath("scripts").glob("*.ps1"))
    for path in paths:
        literal = "'" + str(path).replace("'", "''") + "'"
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command",
             f"$tokens=$null; $errors=$null; "
             f"[void][System.Management.Automation.Language.Parser]::ParseFile({literal}, "
             "[ref]$tokens, [ref]$errors); if ($errors.Count) { "
             "$errors | ForEach-Object { Write-Error $_ }; exit 1 }"],
            capture_output=True, text=True, timeout=30, check=False)
        assert result.returncode == 0, result.stderr


def test_busy_port_fails_before_starting_child(tmp_path):
    executable = shutil.which("pwsh")
    assert executable, "PowerShell 7 is required."
    (tmp_path / ".local").mkdir()
    (tmp_path / ".local/azd-env.ps1").write_text("# offline empty config\n")
    import os
    python_path = tmp_path / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    python_path.parent.mkdir(parents=True)
    python_path.write_text("This must never execute.")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-File",
             str(ROOT / "scripts/start.ps1"), "-ProjectRoot", str(tmp_path),
             "-PythonPort", str(port)],
            capture_output=True, text=True, timeout=30, check=False)
        assert result.returncode != 0
        assert "busy" in result.stderr
        assert "owned PID" not in result.stdout
        assert listener.fileno() >= 0
