"""Run the official CLI without authentication under a Finder-like PATH on macOS."""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.services import ai_provider, codex_macos


def main():
    assert sys.platform == "darwin", "This check requires native macOS"
    prefix = Path(os.environ["TSP_CODEX_NPM_ROOT"])
    shim = prefix / "node_modules/@openai/codex/bin/codex.js"
    node = shutil.which("node")
    assert shim.is_file() and node, "Install the pinned official CLI before this check"
    results = []
    with tempfile.TemporaryDirectory(prefix="tsp-codex-mac-") as temp:
        home = Path(temp)
        for layout in (".npm-global/bin", ".nvm/versions/node/v20.0.0/bin"):
            directory = home / layout
            directory.mkdir(parents=True)
            command = directory / "codex"
            command.symlink_to(shim)
            node_link = directory / "node"
            node_link.symlink_to(node)
            env = {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": str(home),
                "CODEX_HOME": str(home / "isolated-codex-home"),
            }
            with (
                patch.object(Path, "home", return_value=home),
                patch.object(codex_macos, "SYSTEM_BIN_DIRS", ()),
                patch.object(codex_macos, "SYSTEM_DESKTOP_APPS", ()),
                patch.object(
                    ai_provider, "current_codex_command", return_value="codex"
                ),
                patch.dict(os.environ, env, clear=True),
            ):
                assert shutil.which("codex") is None
                assert ai_provider._resolve_command("codex") == str(command)
                assert ai_provider.codex_cli_available(), (
                    f"Version probe failed for {layout}"
                )
                code, out, err = ai_provider._run_codex_process(
                    [str(command), "exec", "--help"], "", env, 30
                )
                assert code == 0 and b"--model" in out, err.decode(errors="replace")
                assert os.environ["PATH"] == env["PATH"]
                results.append(
                    {"layout": layout, "version_probe": True, "exec_help": True}
                )
            command.unlink()
            node_link.unlink()
    print(
        json.dumps(
            {
                "native_macos": True,
                "cli_version": "0.163.0",
                "authenticated_model_request": False,
                "checks": results,
            }
        )
    )


if __name__ == "__main__":
    main()
