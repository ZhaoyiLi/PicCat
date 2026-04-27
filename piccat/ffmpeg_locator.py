from __future__ import annotations

import os
from pathlib import Path
import shutil


def find_executable(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None

    package_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    if not package_root.exists():
        return None

    matches = sorted(package_root.glob(f"Gyan.FFmpeg*/**/bin/{name}.exe"), reverse=True)
    if matches:
        return str(matches[0])
    return None
