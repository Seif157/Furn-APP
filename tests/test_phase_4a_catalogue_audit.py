"""Static safety tests for the read-only Phase 4A catalogue quality audit."""

import re
from pathlib import Path

from pglast import ast, parse_sql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = PROJECT_ROOT / "sql" / "phase-4a-catalogue-quality-audit.sql"
DOC_PATH = PROJECT_ROOT / "docs" / "phase-4a-catalogue-quality-audit.md"

# Columns whose raw values must never be projected by an aggregate audit.
PRIVATE_COLUMNS = (
    "business_name",
    "user_id",
    "email",
    "phone",
    "address_line",
    "state_reason",
    "customer_profile_id",
)
# Content columns that may only appear inside a length, pattern, grouping, or
# null test, never as a bare projection.
CONTENT_COLUMNS = ("name", "description", "image_url")


def read() -> str:
    return AUDIT_PATH.read_text(encoding="utf-8")


def executable_sql() -> str:
    sql = re.sub(r"/\*.*?\*/", " ", read(), flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


def sections() -> list[str]:
    body = executable_sql()
    parts = [part.strip() for part in body.split(";") if part.strip()]
    return parts


def test_audit_is_twelve_select_only_statements() -> None:
    statements = parse_sql(read())
    assert len(statements) == 12
    assert all(isinstance(raw.stmt, ast.SelectStmt) for raw in statements)
    assert len(re.findall(r"(?m)^-- (?:0[1-9]|1[0-2])\.", read())) == 12
    lowered = re.sub(r"'[^']*'", "''", executable_sql()).lower()
    for forbidden in (
        "begin",
        "commit",
        "rollback",
        "do $",
        "insert into",
        "update ",
        "delete from",
        "create ",
        "alter ",
        "drop ",
        "grant ",
        "revoke ",
        "execute ",
        "set ",
        "select *",
        "service_role",
    ):
        assert forbidden not in lowered, forbidden


def _output_targets(select: ast.SelectStmt) -> list[ast.ResTarget]:
    """Target lists of the statement's final output, across set operations."""

    if select.larg is None and select.rarg is None:
        return list(select.targetList or ())
    return _output_targets(select.larg) + _output_targets(select.rarg)


def _column_paths(node: object) -> list[tuple[str, ...]]:
    """Every ColumnRef reachable from a projected expression."""

    if isinstance(node, ast.ColumnRef):
        return [
            tuple(field.sval for field in node.fields if isinstance(field, ast.String))
        ]
    paths: list[tuple[str, ...]] = []
    if isinstance(node, ast.Node):
        for attribute in node.__slots__:
            paths.extend(_column_paths(getattr(node, attribute)))
    elif isinstance(node, list | tuple):
        for item in node:
            paths.extend(_column_paths(item))
    return paths


def _contains_call(node: object) -> bool:
    if isinstance(node, ast.FuncCall):
        return True
    if isinstance(node, ast.Node):
        return any(_contains_call(getattr(node, slot)) for slot in node.__slots__)
    if isinstance(node, list | tuple):
        return any(_contains_call(item) for item in node)
    return False


def test_audit_never_projects_private_or_raw_content_columns() -> None:
    lowered = executable_sql().lower()
    for column in PRIVATE_COLUMNS:
        assert column not in lowered, column
    for raw in parse_sql(read()):
        for target in _output_targets(raw.stmt):
            if isinstance(target.val, ast.ColumnRef):
                path = tuple(
                    field.sval
                    for field in target.val.fields
                    if isinstance(field, ast.String)
                )
                assert path[-1] not in CONTENT_COLUMNS or path == (
                    "category",
                    "name",
                ), path
                assert path[-1] != "id", path
                assert not path[-1].endswith("_id"), path
            else:
                # Content columns and identifiers may feed only aggregates,
                # lengths, and patterns; the output expression must contain a
                # function call, never be a bare column or a plain cast of one.
                for path in _column_paths(target.val):
                    if path[-1] in ("image_url", "id") or path[-1].endswith("_id"):
                        assert _contains_call(target.val), path


def test_audit_covers_every_normalization_target() -> None:
    sql = read().lower()
    for column in (
        "width_cm",
        "height_cm",
        "depth_cm",
        "weight_kg",
        "materials",
        "color_value",
        "category.name",
        "attribute_kind",
        "attribute_value",
        "is_primary",
        "discount_price",
        "lifecycle_state",
    ):
        assert column in sql, column
    assert "jsonb_typeof" not in sql  # attribute_value is text, confirmed live
    assert "then 'json_like'" in sql and "then 'number'" in sql
    assert "percentile_cont" in sql
    assert "limit 500" in sql
    assert sql.count("'published'::public.product_state") >= 8
    assert "stock_quantity > 0" in sql
    assert "party_confirmed" in sql and "ai_proposed" in sql
    arabic_range = "[" + chr(0x0600) + "-" + chr(0x06FF) + "]"
    assert sql.count(arabic_range) == 2  # Arabic script detection in name/description


def test_document_matches_the_audit() -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    assert "Status: **Audit package ready for a read-only run; not yet run.**" in doc
    assert "docs/evidence/phase-4a/section-NN.csv" in doc
    for number in range(1, 13):
        assert f"| {number:02d} |" in doc, number
    assert "no product name, description, image URL, or row UUID" in doc
    assert "Phase 4B" in doc
    assert "four recommendation-eligible products" in doc
    assert "## Run record (2026-09-16)" in doc
    assert "Sections 09 and 10 returned zero rows" in doc


EVIDENCE = PROJECT_ROOT / "docs" / "evidence" / "phase-4a"
EXPECTED_HEADERS = {
    "01": "table_name,ordinal_position,column_name,formatted_type,is_not_null,"
    "default_expression,generated_kind",
    "02": "measure,bucket,product_count",
    "03": "measure,product_count,null_count,non_positive_count,minimum,median,"
    "maximum,over_1000_count",
    "04": "published_count,non_positive_price_count,discounted_count,"
    "discount_not_below_price_count,non_positive_discount_count,minimum_price,"
    "median_price,maximum_price",
    "05": "row_kind,material,product_count",
    "06": "category_name,is_active,total_products,published_products,"
    "in_stock_published_products",
    "07": "row_kind,colour,colour_rows,product_count,in_stock_rows",
    "08": "published_products,without_images,without_primary,multiple_primary,"
    "with_non_https_urls,with_colour_linked_images,minimum_images,median_images,"
    "maximum_images",
    "11": "published_products,short_names,missing_descriptions,short_descriptions,"
    "names_with_units,descriptions_with_units,names_with_arabic,"
    "descriptions_with_arabic,median_name_length,median_description_length,"
    "duplicate_name_groups",
    "12": "check_name,expected_count,actual_count,failed_count,check_passed",
}


def test_saved_evidence_has_exact_headers_and_documented_facts() -> None:
    import csv

    saved = sorted(path.name for path in EVIDENCE.glob("section-*.csv"))
    assert saved == [f"section-{number}.csv" for number in EXPECTED_HEADERS]
    tables: dict[str, list[str]] = {}
    for number, header in EXPECTED_HEADERS.items():
        with (EVIDENCE / f"section-{number}.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            reader = csv.DictReader(handle)
            assert ",".join(reader.fieldnames or ()) == header, number
            rows = list(reader)
        assert 0 < len(rows) < 100, number
        if number == "01":
            for row in rows:
                tables.setdefault(row["table_name"], []).append(row["column_name"])
        if number == "02":
            assert {(r["bucket"], r["product_count"]) for r in rows} == {
                ("recommendation_eligible", "4"),
                ("published", "4"),
            }
        if number == "03":
            by_measure = {r["measure"]: r for r in rows}
            assert by_measure["weight_kg"]["null_count"] == "4"
            assert all(
                by_measure[m]["null_count"] == "0"
                for m in ("width_cm", "height_cm", "depth_cm")
            )
        if number == "12":
            assert rows[0]["check_passed"] == "true"
    assert set(tables) == {
        "category",
        "product",
        "product_3d_model",
        "product_color",
        "product_enrichment_assignment",
        "product_enrichment_attribute",
        "product_image",
    }
    assert "parent_id" in tables["category"]
    assert "sku" in tables["product"]
    assert tables["product_enrichment_attribute"] == [
        "id",
        "attribute_kind",
        "attribute_value",
    ]
