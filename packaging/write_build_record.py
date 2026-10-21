"""Write checksum and provenance beside a CI installer without publishing it."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--smoke-report", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    artifact = args.artifact.resolve(strict=True)
    actual_version = json.loads((root / "frontend/package.json").read_text())["version"]
    if args.version != actual_version:
        raise SystemExit("Artifact version does not match frontend/package.json")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True,
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or commit != os.environ["GITHUB_SHA"]:
        raise SystemExit("Checked-out source does not match this Actions run")
    smoke = None
    if args.platform == "windows":
        if args.smoke_report is None:
            raise SystemExit("A passing Windows installer smoke report is required")
        smoke = json.loads(args.smoke_report.read_text(encoding="utf-8"))
        if smoke.get("status") != "passed" or smoke.get("version") != args.version:
            raise SystemExit("Windows installer verification did not pass")
    checksum = file_sha256(artifact)
    if smoke is not None and smoke.get("installer_sha256") != checksum:
        raise SystemExit("The verified installer differs from the artifact")
    repository = os.environ["GITHUB_REPOSITORY"]
    record = {
        "schema_version": 1,
        "version": args.version,
        "platform": args.platform,
        "source": {"repository": repository, "commit": commit, "ref": os.environ["GITHUB_REF"]},
        "build": {
            "time_utc": datetime.now(UTC).isoformat(),
            "run_url": f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
            "attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
            "python": platform.python_version(),
            "machine": platform.machine(),
            "pyinstaller": importlib.metadata.version("pyinstaller"),
        },
        "artifact": {"name": artifact.name, "bytes": artifact.stat().st_size, "sha256": checksum},
        "verification": smoke if smoke is not None else {"status": "not_run", "reason": "Windows installer check is platform-specific"},
    }
    Path(str(artifact) + ".sha256").write_text(f"{checksum}  {artifact.name}\n", encoding="utf-8")
    Path(str(artifact) + ".build.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(f"Prepared {artifact.name}: {checksum}; source {commit}")


if __name__ == "__main__":
    main()
