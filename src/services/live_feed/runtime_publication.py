"""Atomic JSON publication for the three OpenD runtime evidence files.

Concurrent writers cannot share staging files. Publication is last-replace-wins,
not a multi-file transaction or a substitute for runtime/sequence validation.
The caller must surface failures; this module never manufactures health evidence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Mapping


def write_runtime_json(path: str | os.PathLike[str], payload: Mapping) -> None:
    # Reject invalid JSON before touching the last published evidence.
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(destination.stat().st_mode)
    except FileNotFoundError:
        mode = 0o644
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            # Preserve stricter existing permissions; new quote-only files use
            # the former default 0644 so separate reader services retain access.
            if os.name == "posix":
                os.fchmod(handle.fileno(), mode)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        if os.name == "posix":
            directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        # Remove only this writer's staging file; never another writer's file.
        Path(temporary).unlink(missing_ok=True)
