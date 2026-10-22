"""Read-only network preflight before spending time building a desktop installer."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--category', default='etf')
    args = parser.parse_args()
    # Never use a developer's credentials or application data for this check.
    with tempfile.TemporaryDirectory(prefix='tsp-live-preflight-') as folder:
        data = Path(folder)
        env_file = data / 'empty.env'
        env_file.write_text('', encoding='utf-8')
        os.environ.update(DATA_DIR=str(data), TICKFLOW_ENV_FILE=str(env_file),
                          TICKFLOW_API_KEY='', FUYAO_API_KEY='')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
        from app.services.multi_asset_market import snapshot

        print(f'Network preflight: {args.category}', flush=True)
        result = snapshot(args.category, force=True)
        if not result['rows']:
            raise RuntimeError(f'{args.category}: no timestamped public quotes')
        print(json.dumps({'category': args.category, 'rows': len(result['rows']),
                          'attempts': result['attempts'], 'warnings': result['warnings'],
                          'first_source_time': result['rows'][0]['quote_at']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
