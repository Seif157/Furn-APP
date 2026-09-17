"""Tests for the real products' image replacement.

This script is the only thing in the repository that writes to real
marketplace rows, so its guards are tested rather than trusted.
"""

from pglast import ast, parse_sql

from tests import real_product_images as real
from tests import seed_catalogue as seed


def test_rendered_sql_is_byte_identical_to_the_generator() -> None:
    assert real.REAL_IMAGES_SQL_PATH.read_text(encoding="utf-8") == real.render_sql()


def test_the_script_can_only_update_and_only_inside_a_transaction() -> None:
    sql = real.REAL_IMAGES_SQL_PATH.read_text(encoding="utf-8")
    statements = parse_sql(sql)
    assert isinstance(statements[0].stmt, ast.TransactionStmt)
    assert isinstance(statements[-1].stmt, ast.TransactionStmt)
    assert sql.count("UPDATE public.product_image") == 1
    for forbidden in ("INSERT", "DELETE", "DROP", "TRUNCATE", "ALTER", "GRANT"):
        assert forbidden not in sql, forbidden
    assert "service_role" not in sql


def test_the_update_cannot_touch_a_genuine_seller_photograph() -> None:
    # The whole reason this is safe to keep: once a real photo replaces the
    # placeholder, the WHERE clause stops matching that row for good.
    sql = real.REAL_IMAGES_SQL_PATH.read_text(encoding="utf-8")
    assert "AND target.image_url LIKE '%picsum.photos%';" in sql


def test_the_update_is_bounded_to_five_known_image_ids() -> None:
    sql = real.REAL_IMAGES_SQL_PATH.read_text(encoding="utf-8")
    assert len(real.REAL_IMAGES) == 5
    assert len({image.image_id for image in real.REAL_IMAGES}) == 5
    for image in real.REAL_IMAGES:
        assert f"'{image.image_id}'::uuid" in sql
    assert sql.count("::uuid") == 5


def test_every_photo_is_real_and_unused_by_the_seed() -> None:
    seed_photos = {
        photo for photos in seed.CATEGORY_PHOTOS.values() for photo in photos
    }
    photo_ids = [image.photo_id for image in real.REAL_IMAGES]
    assert len(set(photo_ids)) == len(photo_ids)
    for image in real.REAL_IMAGES:
        assert image.url.startswith("https://images.unsplash.com/photo-")
        assert "picsum" not in image.url and "placehold" not in image.url
        # Reusing a seed photo would make a real product look like a fake one.
        assert image.photo_id not in seed_photos
