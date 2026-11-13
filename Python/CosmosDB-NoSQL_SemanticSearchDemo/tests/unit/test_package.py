import importlib.util
from pathlib import Path
import zipfile


def test_deployment_archive_uses_allowlist(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/package-app.py"
    spec = importlib.util.spec_from_file_location("package_app", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "sample"
    (root / "src/app").mkdir(parents=True)
    (root / "src/app/cosmos-app.py").write_text("print('app')", encoding="utf-8")
    (root / "src/app/requirements.txt").write_text("streamlit", encoding="utf-8")
    (root / "requirements.txt").write_text("-r src/app/requirements.txt", encoding="utf-8")
    (root / ".env").write_text("SECRET=never-package", encoding="utf-8")
    (root / "src/app/private.env").write_text("SECRET=never-package", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv/example.py").write_text("secret", encoding="utf-8")
    target = tmp_path / "app.zip"
    module.package(root, target)
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == {
            "requirements.txt", "src/app/cosmos-app.py", "src/app/requirements.txt"}
