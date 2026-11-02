"""Copy existing local monitor data to the installed app without overwriting it."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil

try:
    from .desktop_state import load_state, save_state
except ImportError:
    from desktop_state import load_state, save_state


def migrate(source: Path, destination: Path) -> dict:
    if source.resolve() == destination.resolve():
        raise ValueError("旧项目目录和数据目录不能相同")
    destination.mkdir(parents=True, exist_ok=True)
    state = destination / "settings.json"
    if not state.exists():
        saved = load_state(source / "reports" / ".geo-ui-state.json", source / "reports" / ".geo-current-task.json")
        if saved:
            save_state(state, saved)
    copied = 0
    for old_root, new_root in ((source / "reports", destination / "reports"),
                               (source / "services" / "browser-service" / "data" / "browser_sessions",
                                destination / "browser_sessions")):
        if not old_root.exists():
            continue
        for old in old_root.rglob("*"):
            if not old.is_file() or any(part.startswith(".before-") for part in old.relative_to(old_root).parts):
                continue
            new = new_root / old.relative_to(old_root)
            if not new.exists():
                new.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old, new)
                copied += 1
    return {"copied_files": copied, "settings_restored": state.exists()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "GEO-Monitor")
    arguments = parser.parse_args()
    print(migrate(arguments.source, arguments.destination))
