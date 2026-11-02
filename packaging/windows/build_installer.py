"""Build an offline Windows installer with a relocatable Python runtime."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.0.19"
BUILD = ROOT / "build" / "windows" / f"release-{VERSION}"
PAYLOAD = BUILD / "payload"
OUTPUT = ROOT / "dist" / "windows"
EXCLUDE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".env", ".env.*")


def copytree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=EXCLUDE)


def sync_app() -> None:
    app = PAYLOAD / "app"
    app.mkdir(parents=True, exist_ok=True)
    for name in ("GEO-Monitor.pyw", "geo_monitor_gui.pyw", "QUICKSTART.md", "LICENSE"):
        shutil.copy2(ROOT / name, app / name)
    assets = app / "assets"
    assets.mkdir(exist_ok=True)
    for name in ("geo-logo-48.png", "geo-logo-256.png", "geo-logo.ico"):
        shutil.copy2(ROOT / "assets" / name, assets / name)
    tools = app / "tools"
    tools.mkdir(exist_ok=True)
    for path in (ROOT / "tools").glob("*.py"):
        shutil.copy2(path, tools / path.name)
    browser = app / "services" / "browser-service"
    copytree(ROOT / "services" / "browser-service" / "app", browser / "app")
    shutil.copy2(ROOT / "services" / "browser-service" / "manual_login.py", browser / "manual_login.py")
    copytree(ROOT / "services" / "telemetry-service" / "app", app / "services" / "telemetry-service" / "app")


def compile_launcher() -> None:
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/reference:System.Windows.Forms.dll",
                    "/win32icon:" + str(ROOT / "assets" / "geo-logo.ico"),
                    "/out:" + str(PAYLOAD / "GEO-Monitor.exe"), str(Path(__file__).with_name("Launcher.cs"))], check=True)


def check_payload() -> None:
    forbidden = [str(p.relative_to(PAYLOAD)) for p in PAYLOAD.rglob("*")
                 if p.name in {"settings.json", "auth.json", ".geo-current-task.json", ".geo-ui-state.json",
                               "geo-record.local.json", "results.json", "record.html", "record.md", "direct_url.json"}
                 or p.name == ".env" or p.name.startswith(".env.")
                 or any(part in {"browser_sessions", ".codex", ".cc-switch", "User Data"} for part in p.parts)]
    if forbidden:
        raise RuntimeError(f"安装包含个人数据：{forbidden}")
    for path in (PAYLOAD / "app").rglob("*"):
        if path.is_file() and path.suffix in {".py", ".pyw"}:
            text = path.read_text(encoding="utf-8-sig")
            if re.search(r"\bsk-[A-Za-z0-9_-]{20,}", text):
                raise RuntimeError(f"安装包源文件疑似含密钥：{path.relative_to(PAYLOAD)}")
    unexpected = {p.name for p in (PAYLOAD / "app").iterdir()} - {
        "GEO-Monitor.pyw", "geo_monitor_gui.pyw", "QUICKSTART.md", "LICENSE", "assets", "tools", "services",
    }
    if unexpected:
        raise RuntimeError(f"安装包包含未允许的应用内容：{sorted(unexpected)}")


def build_payload() -> None:
    """Use an explicit allowlist so no reports, keys or cookies enter the package."""
    if PAYLOAD.exists():
        raise RuntimeError(f"构建目录已存在，请使用新的构建目录或确认后清理：{PAYLOAD}")
    PAYLOAD.mkdir(parents=True)
    sync_app()

    runtime = PAYLOAD / "runtime"
    base = Path(sys.base_prefix)
    runtime.mkdir()
    for path in base.iterdir():
        if path.is_file() and path.suffix in {".exe", ".dll"} or path.name == "LICENSE.txt":
            shutil.copy2(path, runtime / path.name)
    for name in ("DLLs", "tcl"):
        copytree(base / name, runtime / name)
    shutil.copytree(base / "Lib", runtime / "Lib", ignore=shutil.ignore_patterns(
        "site-packages", "test", "tests", "__pycache__", "*.pyc", "*.pyo"))
    packages = Path(sys.prefix) / "Lib" / "site-packages"
    shutil.copytree(packages, runtime / "Lib" / "site-packages", ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", "*.pyo", "*.pth", "_virtualenv.py", "*.egg-link", "direct_url.json"))
    for path in (runtime / "Lib" / "site-packages").glob("geo_checker*.dist-info"):
        shutil.rmtree(path)

    cache = Path(os.environ["LOCALAPPDATA"]) / "ms-playwright"
    browsers: set[str] = set()
    for package in ("playwright", "patchright"):
        spec = json.loads((packages / package / "driver" / "package" / "browsers.json").read_text())
        for item in spec["browsers"]:
            if item["name"] in {"chromium", "chromium-headless-shell", "ffmpeg"}:
                browsers.add(f"{item['name'].replace('-', '_')}-{item['revision']}")
    for name in sorted(browsers):
        if not (cache / name).is_dir():
            raise RuntimeError(f"构建所需浏览器缺失：{name}")
        copytree(cache / name, PAYLOAD / "browsers" / name)

    compile_launcher()
    check_payload()
    (PAYLOAD / "BUILD.json").write_text(json.dumps({
        "version": VERSION, "python": sys.version.split()[0], "browsers": sorted(browsers),
        "built_at": datetime.now(timezone.utc).isoformat(), "personal_data": False,
    }, indent=2), encoding="utf-8")
    print(f"可安装程序目录：{PAYLOAD}", flush=True)


def main() -> None:
    global BUILD, PAYLOAD, OUTPUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--iscc", type=Path, required=True)
    parser.add_argument("--reuse-payload", action="store_true")
    parser.add_argument("--build-dir", type=Path, default=BUILD)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    BUILD = args.build_dir.resolve()
    PAYLOAD = BUILD / "payload"
    OUTPUT = args.output_dir.resolve()
    if not args.reuse_payload:
        build_payload()
    else:
        if not PAYLOAD.is_dir():
            raise RuntimeError(f"构建目录不存在：{PAYLOAD}")
        sync_app()
        compile_launcher()
        check_payload()
        metadata_file = PAYLOAD / "BUILD.json"
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        metadata["version"] = VERSION
        metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(args.iscc), "/DPayloadDir=" + str(PAYLOAD), "/DOutputDir=" + str(OUTPUT),
                    "/DReleaseVersion=" + VERSION,
                    str(Path(__file__).with_name("GEO-Monitor.iss"))], check=True)
    installer = OUTPUT / f"GEO-Monitor-Setup-{VERSION}.exe"
    with installer.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    installer.with_suffix(".exe.sha256").write_text(f"{digest}  {installer.name}\n", encoding="ascii")
    print(f"安装包：{installer}", flush=True)


if __name__ == "__main__":
    main()
