"""Package only application code and dependency manifests, never local settings."""

from pathlib import Path
import zipfile


def package(root, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    files = [root / "requirements.txt", root / "src/app/requirements.txt"]
    files += sorted((root / "src").rglob("*.py"))
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in files:
            if any(part.startswith(".") or part == "__pycache__"
                   for part in source.relative_to(root).parts):
                continue
            archive.write(source, source.relative_to(root).as_posix())


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    target = root / ".local/app.zip"
    package(root, target)
    print("Created .local/app.zip from the code/manifest allowlist. Inspect before deployment.")
