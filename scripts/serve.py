#!/usr/bin/env python3
"""Serve the read-only PerkWatch API on localhost."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the PerkWatch app API")
    parser.add_argument("--data-dir", type=Path, help="prepared data root")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        import uvicorn
        from perk_watch.api.app import create_app
    except ImportError as error:
        parser.error(f"install the UI dependencies first: {error}")
    uvicorn.run(create_app(args.data_dir), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
