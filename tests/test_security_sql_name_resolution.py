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


SECURITY_SQL = sorted(SQL_DIR.glob("phase-3.2[bcd]-security-hardening*.sql"))

# SQL-standard spellings that PostgreSQL accepts only unqualified. Qualified,
# the real names are bool, int4, int2, int8, float4, float8 and numeric, so
# `pg_catalog.boolean` fails with 42704, which stopped the first live run of
# the 3.2C migration on 2026-09-18.
KEYWORD_ONLY_TYPE = re.compile(
    r"pg_catalog\.(boolean|integer|int|smallint|bigint|real|decimal|dec|float"
    r"|double precision|character varying|character)\b"
)


@pytest.mark.parametrize("path", SECURITY_SQL, ids=lambda path: path.name)
def test_no_keyword_only_type_is_schema_qualified(path: Path) -> None:
    found = sorted(set(KEYWORD_ONLY_TYPE.findall(path.read_text(encoding="utf-8"))))
    assert found == [], f"use the pg_catalog type name instead: {found}"


@pytest.mark.parametrize("path", SECURITY_SQL, ids=lambda path: path.name)
def test_an_empty_search_path_is_matched_in_both_stored_spellings(path: Path) -> None:
    # SET search_path = '' is stored as search_path="" because search_path is a
    # quoted list setting. A check that accepts only 'search_path=' fails on a
    # correctly configured function, and the migration rolls back.
    text = path.read_text(encoding="utf-8")
    exact_only = re.findall(
        r"(?:=|IS DISTINCT FROM)\s*ARRAY\['search_path='\]::text\[\]", text
    )
    assert exact_only == []


# aclexplode rejects a zero-dimensional array with 22023 "ACL arrays must be
# one-dimensional", and ARRAY[] is zero-dimensional. It is STRICT, so a NULL
# list already yields no rows. This form stopped the first live run of the
# 3.2C migration in its postflight. 3.2B concatenates with acldefault() first,
# which is safe, and does not match.
STANDALONE_EMPTY_ACL = re.compile(
    r"aclexplode\(\s*COALESCE\(\s*[a-z_.]+\s*,\s*"
    r"ARRAY\[\]::(?:pg_catalog\.)?aclitem\[\]\s*\)\s*\)"
)


@pytest.mark.parametrize("path", SECURITY_SQL, ids=lambda path: path.name)
def test_aclexplode_is_never_given_a_standalone_empty_array(path: Path) -> None:
    assert STANDALONE_EMPTY_ACL.findall(path.read_text(encoding="utf-8")) == []


def test_the_check_would_catch_the_original_bug() -> None:
    assert STANDALONE_EMPTY_ACL.search(
        "pg_catalog.aclexplode(\n    COALESCE(attribute.attacl, "
        "ARRAY[]::pg_catalog.aclitem[])\n) AS acl"
    )
    assert not STANDALONE_EMPTY_ACL.search("pg_catalog.aclexplode(attribute.attacl)")
    assert KEYWORD_ONLY_TYPE.findall("RETURNS pg_catalog.boolean")
    assert KEYWORD_ONLY_TYPE.findall("affected_rows pg_catalog.integer;")
    assert not KEYWORD_ONLY_TYPE.findall("RETURNS pg_catalog.bool")
    assert not KEYWORD_ONLY_TYPE.findall("x pg_catalog.int4; y pg_catalog.timestamptz")
    assert UNQUALIFIED_RELATION.findall("('review'::pg_catalog.regclass, 'id'::name)")
    assert not UNQUALIFIED_RELATION.findall(
        "('public.review'::pg_catalog.regclass, 'id'::name)"
    )
    # A policy's stored text quoted inside a literal is not a lookup.
    assert STRING_LITERAL.sub("", "'x ''submitted''::offer_state'") == ""
