from __future__ import annotations

import getpass
import os
import stat
import subprocess
from pathlib import Path


def restrict_private_permissions(path: Path, mode: int) -> None:
    if mode not in {0o600, 0o700}:
        raise ValueError("private paths must use mode 0600 or 0700")
    os.chmod(path, mode)
    if os.name != "nt":
        return

    user = os.getenv("USERNAME") or getpass.getuser()
    grant = f"{user}:(OI)(CI)(F)" if path.is_dir() else f"{user}:(F)"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", grant],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    if completed.returncode != 0:
        raise PermissionError(f"unable to restrict Windows ACL: {path}")


def require_private_permissions(path: Path, mode: int) -> None:
    if os.name == "nt":
        restrict_private_permissions(path, mode)
        return
    if stat.S_IMODE(path.stat().st_mode) != mode:
        raise PermissionError(f"private path must have mode {mode:04o}: {path}")
