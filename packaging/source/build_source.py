"""Export desktop sources using a file allowlist; never copy local user data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.0.11"
SKIP = {"__pycache__", ".git", ".venv", "node_modules", "data", "reports", "output"}


def selected_files():
    for name in ("GEO-Monitor.pyw", "geo_monitor_gui.pyw", "QUICKSTART.md", "LICENSE"):
        yield ROOT / name
    for directory, pattern in (("tools", "*.py"), ("assets", "*"),
                               ("tests", "test_*.py"), ("packaging/windows", "*"),
                               ("packaging/source", "*")):
        for path in sorted((ROOT / directory).glob(pattern)):
            if path.is_file():
                yield path
    yield ROOT / "services/browser-service/pyproject.toml"
    yield ROOT / "services/browser-service/manual_login.py"
    for path in sorted((ROOT / "services/browser-service/app").rglob("*")):
        if path.is_file() and not SKIP.intersection(path.relative_to(ROOT).parts):
            if path.suffix in {".py", ".wasm"}:
                yield path
    for name in ("__init__.py", "qualified_report.py", "brand_mentions.py"):
        yield ROOT / "services/telemetry-service/app" / name


def verify_clean(tree: Path):
    private_names = {"settings.json", "auth.json", "geo-record.local.json", "results.json",
                     "record.html", "record.md", "direct_url.json"}
    for path in tree.rglob("*"):
        relative = path.relative_to(tree)
        if path.is_symlink() or SKIP.intersection(relative.parts):
            raise ValueError(f"Unexpected source item: {relative}")
        if path.name in private_names or path.name == ".env" or path.name.startswith(".env."):
            raise ValueError(f"Private configuration in source: {relative}")
        if not path.is_file() or path.suffix in {".wasm", ".png", ".ico"}:
            continue
        content = path.read_text(encoding="utf-8-sig")
        if re.search(r"\bsk-[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", content):
            raise ValueError(f"Possible credential in source: {relative}")
        # Personal source-machine paths should never be required by a recipient.
        if re.search(r"[CD]:[\\/]+Users[\\/]+EDY|D:[\\/]+geo[\\/]", content, re.I):
            raise ValueError(f"Source-machine path in source: {relative}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/source")
    parser.add_argument("--stage-dir", type=Path, default=ROOT / "build/source" / f"release-{VERSION}")
    args = parser.parse_args()
    stage = args.stage_dir.resolve() / f"GEO-Monitor-Source-{VERSION}"
    if stage.exists():
        raise ValueError("Source staging directory already exists; choose another --stage-dir")
    stage.mkdir(parents=True)
    for path in selected_files():
        relative = path.relative_to(ROOT)
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if relative.parts[0] == "tests":
            text = path.read_text(encoding="utf-8-sig")
            # Generic fixtures retain test behavior without exporting a user's task.
            text = text.replace("\u5ea6\u4e98", "示例品牌").replace("\u5ea6\u66f4", "示例品牌")
            text = re.sub(r"https://www\.toutiao\.com/article/\d+/",
                          "https://publisher.example/article/example-article/", text)
            text = re.sub(r"https://m\.toutiao\.com/i\d+/",
                          "https://m.publisher.example/article/example-article/", text)
            destination.write_text(text, encoding="utf-8")
        else:
            shutil.copy2(path, destination)
    shutil.copy2(ROOT / "packaging/source/README.md", stage / "README.md")
    shutil.copy2(ROOT / "packaging/source/requirements-desktop.txt", stage / "requirements.txt")
    ignored_distributions = {"geo-checker", "browser-service"}
    frozen = sorted({f"{dist.metadata['Name']}=={dist.version}" for dist in metadata.distributions()
                     if dist.metadata["Name"].lower() not in ignored_distributions})
    (stage / "requirements-lock.txt").write_text(
        "# Captured from the desktop release build environment; no local paths.\n"
        + "\n".join(frozen) + "\n", encoding="utf-8")
    (stage / ".gitignore").write_text(
        ".venv/\n__pycache__/\n*.py[cod]\n.env\n.env.*\nsettings.json\n"
        "geo-record.local.json\nreports/\noutput/\nbuild/\ndist/\n"
        "**/data/\nbrowser_sessions/\n*.log\n*.db\n*.sqlite*\n.vscode/\n.playwright-cli/\n",
        encoding="utf-8")
    verify_clean(stage)
    entries = []
    for path in sorted(stage.rglob("*")):
        if path.is_file():
            entries.append({"path": path.relative_to(stage).as_posix(), "size": path.stat().st_size,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {"version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                "scope": "desktop-monitor", "personal_data": False, "files": entries}
    (stage / "SOURCE-MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    archive = args.output_dir / f"GEO-Monitor-Source-{VERSION}.zip"
    if archive.exists():
        raise ValueError("Source archive already exists; choose another --output-dir")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                target.write(path, path.relative_to(stage.parent).as_posix())
    with zipfile.ZipFile(archive) as target:
        if target.testzip() is not None:
            raise ValueError("Source archive integrity check failed")
    archive.with_suffix(".zip.sha256").write_text(
        f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n", encoding="ascii")
    print(json.dumps({"archive": str(archive.resolve()), "files": len(entries) + 1,
                      "bytes": archive.stat().st_size, "stage": str(stage)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
