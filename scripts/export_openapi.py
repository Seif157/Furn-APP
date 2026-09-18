"""Write docs/openapi.json from the application's own route definitions.

    uv run python -m scripts.export_openapi

The Flutter team can generate a Dart client from this file (for example with
openapi-generator's `dart-dio` generator) instead of hand-writing one.
`tests/test_openapi.py` fails whenever the committed file no longer matches
the code, so the file is never a stale description of a different API.

It only imports the app; no server starts and nothing is contacted.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app

OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    OUTPUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(OUTPUT.parents[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
