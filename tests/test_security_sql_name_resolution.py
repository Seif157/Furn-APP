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


MIGRATIONS_DIR = SQL_DIR.parent / "migrations"


def narrowed_files() -> list[Path]:
    candidates = [*SQL_DIR.glob("phase-3.2*.sql"), *MIGRATIONS_DIR.glob("*.sql")]
    return sorted(
        path for path in candidates if NARROWED.search(path.read_text(encoding="utf-8"))
    )


def test_the_files_that_narrow_lookup_are_found() -> None:
    names = {path.name for path in narrowed_files()}
    assert {
        "phase-3.2c-security-hardening.sql",
        "phase-3.2c-security-hardening-preflight.sql",
        "phase-3.2d-security-hardening.sql",
        "phase-3.2d-security-hardening-preflight.sql",
        "checkout-2026-09-18.sql",
    } <= names


@pytest.mark.parametrize("path", narrowed_files(), ids=lambda path: path.name)
def test_no_unqualified_relation_literal(path: Path) -> None:
    found = sorted(set(UNQUALIFIED_RELATION.findall(path.read_text(encoding="utf-8"))))
    assert found == [], f"qualify with public.: {found}"


SECURITY_SQL = sorted(
    [
        *SQL_DIR.glob("phase-3.2[bcd]-security-hardening*.sql"),
        *MIGRATIONS_DIR.glob("*.sql"),
    ]
)

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


# Verification files run in the SQL Editor, where public is on the search path,
# so pg_policies prints `address`, not `public.address`. A check that requires
# the qualified spelling in policy text fails on a correct policy; this is what
# failed section 11 of the first live 3.2C verification.
QUALIFIED_POLICY_TEXT = re.compile(r"(?:qual|with_check)\s+LIKE\s+'%public\.")


@pytest.mark.parametrize(
    "path",
    sorted(SQL_DIR.glob("phase-3.2[cd]-security-hardening-verify.sql")),
    ids=lambda path: path.name,
)
def test_verification_does_not_require_qualified_policy_text(path: Path) -> None:
    assert QUALIFIED_POLICY_TEXT.findall(path.read_text(encoding="utf-8")) == []


# The reverse trap: a file that narrows the search path prints policy text with
# public. qualifiers, while recorded evidence has none. An exact comparison of
# raw pg_policies text must strip public. first; this stopped the first live
# 3.2D preflight on 2026-09-18 ("replaced policy drift").
RAW_POLICY_TEXT_COMPARED = re.compile(
    r"regexp_replace\(\s*actual\.(?:qual|with_check)\b"
)


@pytest.mark.parametrize("path", narrowed_files(), ids=lambda path: path.name)
def test_narrowed_files_normalize_policy_text_before_exact_comparison(
    path: Path,
) -> None:
    text = path.read_text(encoding="utf-8")
    assert RAW_POLICY_TEXT_COMPARED.findall(text) == []


# A role array written as one element holding a comma makes a role literally
# named "anon,authenticated"; the live 3.2D postflight rejected the correct
# policy on it (2026-09-18).
COMMA_IN_ONE_ROLE = re.compile(r"ARRAY\['[^']*,[^']*'\]::name\[\]")


@pytest.mark.parametrize("path", SECURITY_SQL, ids=lambda path: path.name)
def test_no_role_array_element_contains_a_comma(path: Path) -> None:
    assert COMMA_IN_ONE_ROLE.findall(path.read_text(encoding="utf-8")) == []


def test_the_check_would_catch_the_original_bug() -> None:
    assert COMMA_IN_ONE_ROLE.search("ARRAY['anon,authenticated']::name[]")
    assert not COMMA_IN_ONE_ROLE.search("ARRAY['anon', 'authenticated']::name[]")
    assert RAW_POLICY_TEXT_COMPARED.search(
        "OR pg_catalog.regexp_replace(\n  actual.qual, '\\s+', ' ', 'g')"
    )
    assert QUALIFIED_POLICY_TEXT.search("AND with_check LIKE '%public.address%'")
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
