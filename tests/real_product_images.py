"""Generator for the real products' placeholder-image replacement.

The four real catalogue products shipped with `picsum.photos` URLs, which serve
a random photograph rather than furniture, so a sofa could be illustrated by a
landscape. This replaces those five rows with real furniture photographs.

These are real marketplace rows, not seed rows, which changes the safety rules:

  The update matches only rows whose URL still points at picsum.photos. Once a
  seller uploads a genuine photograph, this script can no longer touch that
  row, so rerunning it later can never destroy real content. That guard is the
  reason this is safe to keep in the repository at all.

  Rows are addressed by image id, read from the live catalogue on 2026-09-17,
  so the script cannot wander onto a row it was not written for.

Every photo id below was fetched and confirmed to return an image; none is a
guess, and none is reused from tests/seed_catalogue.py, so the real products
stay visually distinct from the seed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tests.seed_catalogue import UNSPLASH_RENDER

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_IMAGES_SQL_PATH = PROJECT_ROOT / "seed" / "real-product-images.sql"
PLACEHOLDER_HOST = "picsum.photos"


@dataclass(frozen=True, slots=True)
class RealImage:
    image_id: str
    product: str
    """The product's name, for review only; the update matches on image id."""
    photo_id: str

    @property
    def url(self) -> str:
        return f"https://images.unsplash.com/photo-{self.photo_id}{UNSPLASH_RENDER}"


REAL_IMAGES: tuple[RealImage, ...] = (
    RealImage(
        "2701ae27-e11c-4757-885e-530de385fa0a",
        "كنبة كايرو 3 مقاعد — Cairo 3-Seater Sofa (primary)",
        "1484101403633-562f891dc89a",
    ),
    RealImage(
        "c7d02dc5-e53c-412e-9117-b712d5dacc15",
        "كنبة كايرو 3 مقاعد — Cairo 3-Seater Sofa (secondary)",
        "1590251024078-8a6d9f90b02d",
    ),
    RealImage(
        "fe2eed3a-da45-4266-9c28-46444de65dc0",
        "سرير كينج خشب — King Wooden Bed",
        "1560185893-a55cbc8c57e8",
    ),
    RealImage(
        "00cfd813-4632-4648-941c-c76144ef288a",
        "طاولة سفرة 6 كراسي — 6-Seater Dining Set",
        "1517870662726-c1d98ee36250",
    ),
    RealImage(
        "d88fc80e-6771-46cc-84d6-044151e1cd67",
        "دولاب 4 ضلفة — 4-Door Wardrobe",
        "1509319117193-57bab727e09d",
    ),
)


def render_sql() -> str:
    rows = [
        f"    -- {image.product}\n    ('{image.image_id}'::uuid, '{image.url}')"
        for image in REAL_IMAGES
    ]
    return "\n".join(
        [
            "/*",
            "Replace the real products' placeholder images with real photographs.",
            "",
            "The four real catalogue products shipped with picsum.photos URLs, which",
            "serve a random photograph rather than furniture. This updates those five",
            "rows and nothing else.",
            "",
            "These are real marketplace rows, so the update is doubly bounded: it",
            "matches only the five image ids listed, and only while they still point",
            f"at {PLACEHOLDER_HOST}. Once a seller uploads a genuine photograph this",
            "script can no longer change that row, so a later rerun cannot destroy",
            "real content. Running it twice updates nothing the second time.",
            "",
            "Rendered by tests/real_product_images.py; do not hand-edit.",
            "*/",
            "",
            "BEGIN;",
            "",
            "SET LOCAL lock_timeout = '5s';",
            "SET LOCAL statement_timeout = '2min';",
            "",
            "UPDATE public.product_image AS target",
            "SET image_url = source.image_url",
            "FROM (VALUES",
            ",\n".join(rows),
            ") AS source(id, image_url)",
            "WHERE target.id = source.id",
            f"  AND target.image_url LIKE '%{PLACEHOLDER_HOST}%';",
            "",
            "COMMIT;",
            "",
        ]
    )


if __name__ == "__main__":
    REAL_IMAGES_SQL_PATH.parent.mkdir(exist_ok=True)
    REAL_IMAGES_SQL_PATH.write_text(render_sql(), encoding="utf-8", newline="\n")
    print(
        f"wrote {REAL_IMAGES_SQL_PATH.relative_to(PROJECT_ROOT)} "
        f"({len(REAL_IMAGES)} images)"
    )
