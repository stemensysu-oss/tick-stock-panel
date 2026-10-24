"""Find local CLI installs without executing login profiles or changing global PATH."""

from __future__ import annotations

import os
import re
from pathlib import Path

SYSTEM_BIN_DIRS = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))
SYSTEM_DESKTOP_APPS = (Path("/Applications/Codex.app"),)


def _version_key(path: Path) -> tuple:
    match = re.search(r"[/\\]v?(\d+)\.(\d+)\.(\d+)[/\\]", str(path))
    return tuple(map(int, match.groups())) if match else (0, 0, 0)


def _bin_directories() -> list[Path]:
    home = Path.home()
    directories = [
        *SYSTEM_BIN_DIRS,
        *(
            home / part
            for part in (
                ".local/bin",
                "bin",
                ".npm-global/bin",
                ".volta/bin",
                ".asdf/shims",
                ".asdf/bin",
                ".nvm/current/bin",
                ".fnm/current/bin",
            )
        ),
    ]
    # Search only established Node-manager layouts, never the whole home directory.
    for pattern in (
        ".nvm/versions/node/*/bin",
        ".local/share/fnm/node-versions/*/installation/bin",
        "Library/Application Support/fnm/node-versions/*/installation/bin",
        ".asdf/installs/nodejs/*/bin",
    ):
        try:
            directories.extend(sorted(home.glob(pattern), key=_version_key, reverse=True))
        except OSError:
            continue
    return list(dict.fromkeys(directories))


def resolve() -> str | None:
    candidates = [directory / "codex" for directory in _bin_directories()]
    for app in (*SYSTEM_DESKTOP_APPS, Path.home() / "Applications/Codex.app"):
        candidates.append(app / "Contents/Resources/codex")
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def launch_environment(command: str, env: dict[str, str]) -> dict[str, str]:
    result = dict(env)
    # npm's codex shim may use /usr/bin/env node. Its own bin directory must
    # remain visible for both --version and exec when Finder supplied a short PATH.
    directories = [str(Path(command).parent)]
    directories.extend(part for part in env.get("PATH", "").split(os.pathsep) if part)
    directories.extend(str(p) for p in _bin_directories())
    result["PATH"] = os.pathsep.join(dict.fromkeys(directories))
    return result
