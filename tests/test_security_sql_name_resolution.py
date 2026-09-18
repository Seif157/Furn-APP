"""Every security file that narrows name lookup must qualify what it names.

The 3.2C and 3.2D files start with `SET LOCAL search_path = pg_catalog` so a
hostile object in another schema cannot shadow anything they touch. Under that
setting an unqualified `'review'::pg_catalog.regclass` looks for `review` in
pg_catalog and fails with 42P01. That exact failure stopped the first live run
of the 3.2C preflight on 2026-09-18. No test caught it because nothing here
executes SQL, so this test reads for the pattern directly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
NARROWED = re.compile(
    r"^\s*SET\s+(LOCAL\s+)?search_path\s*=\s*pg_catalog\s*;", re.I | re.M
)
UNQUALIFIED_RELATION = re.compile(r"'([a-z_][a-z0-9_]*)'::(?:pg_catalog\.)?regclass")
STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")


def narrowed_files() -> list[Path]:
    return sorted(
        path
        for path in SQL_DIR.glob("phase-3.2*.sql")
        if NARROWED.search(path.read_text(encoding="utf-8"))
    )


def test_the_files_that_narrow_lookup_are_found() -> None:
    names = {path.name for path in narrowed_files()}
    assert {
        "phase-3.2c-security-hardening.sql",
        "phase-3.2c-security-hardening-preflight.sql",
        "phase-3.2d-security-hardening.sql",
        "phase-3.2d-security-hardening-preflight.sql",
    } <= names


@pytest.mark.parametrize("path", narrowed_files(), ids=lambda path: path.name)
def test_no_unqualified_relation_literal(path: Path) -> None:
    found = sorted(set(UNQUALIFIED_RELATION.findall(path.read_text(encoding="utf-8"))))
    assert found == [], f"qualify with public.: {found}"


def test_the_check_would_catch_the_original_bug() -> None:
    assert UNQUALIFIED_RELATION.findall("('review'::pg_catalog.regclass, 'id'::name)")
    assert not UNQUALIFIED_RELATION.findall(
        "('public.review'::pg_catalog.regclass, 'id'::name)"
    )
    # A policy's stored text quoted inside a literal is not a lookup.
    assert STRING_LITERAL.sub("", "'x ''submitted''::offer_state'") == ""
