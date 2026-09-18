"""The committed OpenAPI file must describe the API the code actually serves."""

from __future__ import annotations

import json

from app.main import app
from scripts.export_openapi import OUTPUT


def test_the_committed_openapi_file_matches_the_code() -> None:
    committed = json.loads(OUTPUT.read_text(encoding="utf-8"))

    assert committed == app.openapi(), (
        "docs/openapi.json is out of date; run "
        "`uv run python -m scripts.export_openapi` and commit the result"
    )


def test_every_route_flutter_uses_is_described() -> None:
    paths = app.openapi()["paths"]

    for path, method in (
        ("/v1/meta", "get"),
        ("/v1/search", "post"),
        ("/v1/search/vocabulary", "get"),
        ("/v1/search/examples", "get"),
        ("/v1/rooms/plan", "post"),
        ("/v1/rooms/image", "post"),
        ("/v1/compare", "post"),
        ("/v1/catalog/products", "get"),
        ("/v1/catalog/products/{product_id}", "get"),
        ("/v1/catalog/products/{product_id}/similar", "get"),
        ("/v1/reviews/public", "get"),
        ("/v1/me", "get"),
        ("/health", "get"),
    ):
        assert method in paths[path], (path, method)
