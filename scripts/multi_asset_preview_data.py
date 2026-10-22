"""Export fictional fixtures through the production service, without user data."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.multi_asset import MultiAssetService  # noqa: E402
from app.services.multi_asset_catalog import catalog  # noqa: E402


def main() -> None:
    metadata = catalog()
    cache = ROOT / "frontend" / "node_modules" / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tsp-preview-", dir=cache) as directory:
        service = MultiAssetService(Path(directory))
        snapshots = {
            category["id"]: {
                mode: service.snapshot(category["id"], mode)
                for mode in ("demo", "imported")
            }
            for category in metadata["categories"]
        }
    print(json.dumps({"catalog": metadata, "snapshots": snapshots}, ensure_ascii=False))


if __name__ == "__main__":
    main()
