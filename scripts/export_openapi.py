"""Export the FastAPI OpenAPI schema to docs/openapi.json.

Usage: .venv/bin/python scripts/export_openapi.py
"""

from __future__ import annotations

import json
from pathlib import Path

from openquyhoach_api.app import create_app


def main() -> None:
    app = create_app()
    schema = app.openapi()
    out = Path("docs/openapi.json")
    out.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
