"""Deterministic fake catalogue for search evaluation and testing-branch seeding.

One definition serves two consumers: the offline tests build normalized
products from it directly, and ``render_seed_sql`` emits the guarded SQL under
``seed/`` that a human runs on the fake-data testing branch. The rows follow
the conventions the Phase 4A audit found in the real catalogue: bilingual
"Arabic — English" category and colour labels, Arabic material tokens, Arabic
names, English descriptions, centimetre dimensions, and published state.

Nothing here contacts a database. Identifiers are fixed so reruns and tests are
reproducible; every product carries a ``SEED-`` SKU so the rows can be removed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_SQL_PATH = PROJECT_ROOT / "seed" / "phase-5-fake-catalogue.sql"
REMOVE_SQL_PATH = PROJECT_ROOT / "seed" / "phase-5-fake-catalogue-remove.sql"
IMAGES_SQL_PATH = PROJECT_ROOT / "seed" / "phase-5-fake-catalogue-images.sql"

CATEGORY_LABELS = {
    "beds": "Beds — أسرّة",
    "dining": "Dining — سفرة",
    "sofas": "Sofas — كنب",
    "wardrobes": "Wardrobes — دواليب",
    "chairs": "Chairs — كراسي",
}
COLOUR_LABELS = {
    "white": "أبيض — white",
    "brown": "بني — brown",
    "dark_brown": "بني غامق — dark brown",
    "beige": "بيج — beige",
    "grey": "رمادي — grey",
    "natural": "طبيعي — natural",
    "navy": "كحلي — navy",
    "wenge": "وينجيه — wenge",
    "black": "أسود — black",
    "cream": "كريمي — cream",
}
MATERIAL_TOKENS = {
    "beech_wood": "خشب زان",
    "wood": "خشب",
    "cotton": "قطن",
    "fabric": "قماش",
    "mdf": "mdf",
    "velvet": "قطيفة",
    "leather": "جلد",
    "metal": "معدن",
    "glass": "زجاج",
    "oak": "بلوط",
    "linen": "كتان",
    "foam": "إسفنج",
}
STYLE_WORDS = {
    "modern": "مودرن",
    "classic": "كلاسيك",
    "scandinavian": "اسكندنافي",
    "industrial": "صناعي",
}


# Real furniture photographs from Unsplash, which serves them under a licence
# that permits commercial use without attribution. Every id below was fetched
# on 2026-09-17 and confirmed to return an image/jpeg body; none is a guess.
# Photo ids are stable, and the rendering parameters are ours, so these URLs do
# not drift. Placeholder images that read "SEED-017" made the catalogue look
# unfinished in a demo, which is the whole reason these exist.
UNSPLASH_RENDER = "?auto=format&fit=crop&w=800&h=600&q=80"
CATEGORY_PHOTOS: dict[str, tuple[str, ...]] = {
    "sofas": (
        "1555041469-a586c61ea9bc",
        "1567016432779-094069958ea5",
        "1573866926487-a1865558a9cf",
        "1512212621149-107ffe572d2f",
        "1550581190-9c1c48d21d6c",
        "1493663284031-b7e3aefcae8e",
        "1519961655809-34fa156820ff",
        "1567016376408-0226e4d0c1ea",
    ),
    "beds": (
        "1564019472231-4586c552dc27",
        "1635594202056-9ea3b497e5c0",
        "1552858725-2758b5fb1286",
        "1617325247661-675ab4b64ae2",
        "1505693416388-ac5ce068fe85",
        "1601276174812-63280a55656e",
        "1552650272-b8a34e21bc4b",
        "1556750539-dc6305f4f248",
    ),
    "dining": (
        "1657524398377-567034729507",
        "1614597445336-8a67e9314d91",
        "1604578762246-41134e37f9cc",
        "1606660023296-81d67734170a",
        "1574966739987-65e38db0f7ce",
        "1605239435870-67df4c54a0b3",
        "1615066390971-03e4e1c36ddf",
        "1602872030490-4a484a7b3ba6",
    ),
    "wardrobes": (
        "1672137233327-37b0c1049e77",
        "1567401893414-76b7b1e5a7a5",
        "1649361811423-a55616f7ab11",
        "1558997519-83ea9252edf8",
        "1614631446501-abcf76949eca",
        "1611048268330-53de574cae3b",
        "1558769132-cb1aea458c5e",
        "1567113463300-102a7eb3cb26",
    ),
    "chairs": (
        "1580480055273-228ff5388ef8",
        "1506439773649-6e0eb8cfb237",
        "1612372606404-0ab33e7187ee",
        "1581539250439-c96689b516dd",
        "1598300042247-d088f8ab3a91",
        "1592078615290-033ee584e267",
        "1549497538-303791108f95",
        "1567538096630-e0c55bd6374c",
    ),
}


@dataclass(frozen=True, slots=True)
class SeedColour:
    slug: str
    stock: int


@dataclass(frozen=True, slots=True)
class SeedProduct:
    number: int
    category: str
    style: str
    name: str
    description: str
    price: Decimal
    discount_price: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None
    depth_cm: Decimal | None
    weight_kg: Decimal | None
    materials: tuple[str, ...]
    colours: tuple[SeedColour, ...]
    lifecycle_state: str = "published"

    @property
    def sku(self) -> str:
        return f"SEED-{self.number:03d}"

    @property
    def id(self) -> str:
        return f"7a000000-0000-4000-8000-{self.number:012d}"

    def colour_id(self, index: int) -> str:
        return f"7b000000-0000-4000-8000-{self.number:09d}{index:03d}"

    def image_id(self, index: int) -> str:
        return f"7c000000-0000-4000-8000-{self.number:09d}{index:03d}"

    @property
    def image_url(self) -> str:
        """A real photograph of this product's category.

        Chosen by product number so the assignment is deterministic and a
        rerun produces the same catalogue. Neighbouring products in a category
        get different photos, which is what stops the grid looking duplicated.
        """

        photos = CATEGORY_PHOTOS[self.category]
        return (
            "https://images.unsplash.com/photo-"
            f"{photos[self.number % len(photos)]}{UNSPLASH_RENDER}"
        )

    @property
    def eligible(self) -> bool:
        return self.lifecycle_state == "published" and any(
            colour.stock > 0 for colour in self.colours
        )


# (category, style, arabic name stem, english description stem, price band,
#  (width, height, depth) in cm, weight, materials, colours)
_TEMPLATES: dict[
    str,
    tuple[
        tuple[
            str,
            str,
            str,
            int,
            tuple[int, int, int],
            int | None,
            tuple[str, ...],
            tuple[str, ...],
        ],
        ...,
    ],
] = {
    "beds": (
        (
            "modern",
            "سرير مودرن 160",
            "Modern platform bed frame with upholstered headboard.",
            12000,
            (170, 110, 210),
            62,
            ("beech_wood", "fabric"),
            ("beige", "grey"),
        ),
        (
            "classic",
            "سرير كلاسيك 180",
            "Classic carved bed frame in solid beech.",
            18500,
            (190, 130, 215),
            78,
            ("beech_wood",),
            ("brown", "dark_brown"),
        ),
        (
            "scandinavian",
            "سرير اسكندنافي 140",
            "Scandinavian bed with slatted headboard and low profile.",
            9800,
            (150, 95, 205),
            48,
            ("wood",),
            ("natural", "white"),
        ),
        (
            "modern",
            "سرير بتخزين 160",
            "Storage bed with hydraulic lift and fabric cover.",
            15900,
            (172, 105, 212),
            85,
            ("mdf", "fabric", "foam"),
            ("grey", "navy"),
        ),
        (
            "industrial",
            "سرير معدن 120",
            "Industrial single bed with a black metal frame.",
            6400,
            (128, 100, 200),
            34,
            ("metal",),
            ("black",),
        ),
        (
            "classic",
            "سرير قطيفة 180",
            "Velvet upholstered king bed with a tall headboard.",
            21000,
            (195, 140, 220),
            90,
            ("velvet", "foam", "wood"),
            ("navy", "cream"),
        ),
        (
            "modern",
            "سرير جلد 160",
            "Leather-look queen bed with a padded headboard.",
            17200,
            (175, 100, 215),
            72,
            ("leather", "mdf"),
            ("white", "black"),
        ),
        (
            "scandinavian",
            "سرير بلوط 180",
            "Oak king bed with a floating nightstand design.",
            24500,
            (200, 90, 220),
            95,
            ("oak",),
            ("natural",),
        ),
    ),
    "dining": (
        (
            "modern",
            "طاولة سفرة 6 كراسي",
            "Six-seat dining table with a tempered glass top.",
            14500,
            (160, 76, 90),
            55,
            ("glass", "metal"),
            ("black", "white"),
        ),
        (
            "classic",
            "سفرة كلاسيك 8 كراسي",
            "Eight-seat classic dining set in carved beech.",
            32000,
            (220, 78, 100),
            120,
            ("beech_wood",),
            ("brown", "dark_brown"),
        ),
        (
            "scandinavian",
            "طاولة سفرة خشب 4 كراسي",
            "Four-seat round dining table in natural wood.",
            8900,
            (110, 75, 110),
            32,
            ("wood",),
            ("natural",),
        ),
        (
            "industrial",
            "سفرة صناعي 6 كراسي",
            "Industrial dining table with a reclaimed wood top.",
            12800,
            (180, 76, 85),
            68,
            ("wood", "metal"),
            ("brown", "black"),
        ),
        (
            "modern",
            "طاولة سفرة قابلة للتمديد",
            "Extendable dining table seating six to eight.",
            16700,
            (160, 76, 90),
            74,
            ("mdf",),
            ("white", "wenge"),
        ),
        (
            "classic",
            "سفرة رخامية 6 كراسي",
            "Marble-look dining table with brass-tone legs.",
            27500,
            (200, 76, 100),
            110,
            ("mdf", "metal"),
            ("cream", "grey"),
        ),
        (
            "scandinavian",
            "طاولة سفرة بلوط 6 كراسي",
            "Oak dining table with tapered legs.",
            19800,
            (180, 75, 90),
            60,
            ("oak",),
            ("natural", "white"),
        ),
        (
            "modern",
            "سفرة مودرن 4 كراسي",
            "Compact modern dining set for small apartments.",
            7600,
            (120, 76, 80),
            40,
            ("mdf", "fabric"),
            ("grey", "beige"),
        ),
    ),
    "sofas": (
        (
            "modern",
            "كنبة مودرن 3 مقاعد",
            "Modern three-seat sofa with deep cushions.",
            13500,
            (220, 85, 95),
            58,
            ("beech_wood", "fabric", "foam"),
            ("beige", "grey"),
        ),
        (
            "classic",
            "كنبة كلاسيك 3 مقاعد",
            "Classic three-seat sofa with carved wooden arms.",
            19500,
            (230, 100, 95),
            75,
            ("beech_wood", "velvet"),
            ("dark_brown", "navy"),
        ),
        (
            "scandinavian",
            "كنبة اسكندنافي مقعدين",
            "Scandinavian two-seat sofa on tapered legs.",
            9900,
            (165, 82, 88),
            42,
            ("wood", "cotton"),
            ("natural", "grey"),
        ),
        (
            "modern",
            "كنبة ركنة",
            "L-shaped corner sofa with a reversible chaise.",
            24000,
            (280, 88, 180),
            110,
            ("mdf", "fabric", "foam"),
            ("grey", "beige", "navy"),
        ),
        (
            "industrial",
            "كنبة جلد مقعدين",
            "Industrial two-seat sofa in leather-look upholstery.",
            11800,
            (170, 80, 90),
            50,
            ("leather", "metal"),
            ("black", "brown"),
        ),
        (
            "modern",
            "كنبة سرير",
            "Sofa bed that converts to a double bed.",
            14200,
            (200, 90, 100),
            70,
            ("mdf", "fabric", "foam"),
            ("grey", "cream"),
        ),
        (
            "classic",
            "كنبة قطيفة 3 مقاعد",
            "Velvet three-seat sofa with tufted back.",
            21500,
            (225, 95, 95),
            80,
            ("velvet", "beech_wood"),
            ("navy", "cream", "beige"),
        ),
        (
            "scandinavian",
            "كنبة كتان 3 مقاعد",
            "Linen three-seat sofa with a slim frame.",
            15800,
            (215, 84, 92),
            55,
            ("linen", "wood"),
            ("white", "beige"),
        ),
    ),
    "wardrobes": (
        (
            "modern",
            "دولاب 3 ضلف",
            "Three-door wardrobe with a mirrored centre panel.",
            16800,
            (150, 210, 60),
            120,
            ("mdf",),
            ("white", "wenge"),
        ),
        (
            "classic",
            "دولاب كلاسيك 4 ضلف",
            "Four-door classic wardrobe in carved beech.",
            28900,
            (200, 220, 65),
            160,
            ("beech_wood",),
            ("brown", "dark_brown"),
        ),
        (
            "scandinavian",
            "دولاب اسكندنافي 2 ضلف",
            "Two-door Scandinavian wardrobe with open shelving.",
            10900,
            (100, 200, 55),
            70,
            ("wood",),
            ("natural", "white"),
        ),
        (
            "modern",
            "دولاب جرار 2 ضلف",
            "Sliding-door wardrobe with a full-height mirror.",
            22500,
            (180, 215, 62),
            140,
            ("mdf", "glass"),
            ("white", "grey"),
        ),
        (
            "industrial",
            "دولاب معدن مفتوح",
            "Open industrial wardrobe with a metal frame.",
            7400,
            (120, 190, 50),
            38,
            ("metal", "wood"),
            ("black",),
        ),
        (
            "modern",
            "دولاب 5 ضلف",
            "Five-door wardrobe with integrated drawers.",
            31000,
            (250, 220, 62),
            190,
            ("mdf",),
            ("cream", "wenge"),
        ),
        (
            "classic",
            "دولاب بلوط 3 ضلف",
            "Oak three-door wardrobe with brass handles.",
            34500,
            (160, 215, 60),
            150,
            ("oak",),
            ("natural",),
        ),
        (
            "scandinavian",
            "دولاب أطفال 2 ضلف",
            "Compact children's wardrobe with rounded edges.",
            6900,
            (90, 170, 50),
            45,
            ("mdf",),
            ("white", "beige"),
        ),
    ),
    "chairs": (
        (
            "modern",
            "كرسي سفرة مودرن",
            "Modern dining chair with a curved fabric seat.",
            1900,
            (46, 88, 52),
            6,
            ("metal", "fabric"),
            ("grey", "beige"),
        ),
        (
            "classic",
            "كرسي كلاسيك منجد",
            "Classic upholstered chair with carved legs.",
            3400,
            (50, 100, 55),
            9,
            ("beech_wood", "velvet"),
            ("navy", "dark_brown"),
        ),
        (
            "scandinavian",
            "كرسي خشب اسكندنافي",
            "Scandinavian wooden chair with a woven seat.",
            2200,
            (45, 82, 50),
            5,
            ("wood", "cotton"),
            ("natural", "white"),
        ),
        (
            "industrial",
            "كرسي معدن صناعي",
            "Stackable industrial metal chair.",
            1200,
            (44, 84, 50),
            5,
            ("metal",),
            ("black",),
        ),
        (
            "modern",
            "كرسي مكتب",
            "Ergonomic office chair with lumbar support.",
            4800,
            (62, 118, 62),
            14,
            ("metal", "fabric", "foam"),
            ("black", "grey"),
        ),
        (
            "classic",
            "كرسي جلد بذراعين",
            "Leather-look armchair for reading corners.",
            7900,
            (80, 95, 85),
            24,
            ("leather", "wood"),
            ("brown", "black"),
        ),
        (
            "modern",
            "كرسي هزاز",
            "Rocking chair with a padded linen cushion.",
            5600,
            (70, 100, 95),
            16,
            ("wood", "linen"),
            ("natural", "cream"),
        ),
        (
            "scandinavian",
            "كرسي طعام بلوط",
            "Oak dining chair with a slim backrest.",
            2900,
            (47, 86, 52),
            6,
            ("oak",),
            ("natural", "white"),
        ),
    ),
}


def _build() -> tuple[SeedProduct, ...]:
    products: list[SeedProduct] = []
    number = 0
    for category, rows in _TEMPLATES.items():
        for style, name, description, price, (
            width,
            height,
            depth,
        ), weight, materials, colours in rows:
            number += 1
            discount = Decimal(price) * Decimal("0.85") if number % 3 == 0 else None
            products.append(
                SeedProduct(
                    number=number,
                    category=category,
                    style=style,
                    name=name,
                    description=description,
                    price=Decimal(price),
                    discount_price=discount.quantize(Decimal("1"))
                    if discount
                    else None,
                    width_cm=Decimal(width),
                    height_cm=Decimal(height),
                    depth_cm=Decimal(depth),
                    weight_kg=None if number % 5 == 0 else Decimal(weight),
                    materials=materials,
                    colours=tuple(
                        SeedColour(slug=slug, stock=(index + number) % 4 + 1)
                        for index, slug in enumerate(colours)
                    ),
                )
            )
    # Ineligible rows that exercise the eligibility filters.
    base = products[0]
    products.append(
        SeedProduct(
            number=41,
            category="sofas",
            style="modern",
            name="كنبة مسودة",
            description="Draft sofa that must never appear in results.",
            price=Decimal(9000),
            discount_price=None,
            width_cm=Decimal(200),
            height_cm=Decimal(85),
            depth_cm=Decimal(90),
            weight_kg=Decimal(50),
            materials=("fabric",),
            colours=(SeedColour("grey", 3),),
            lifecycle_state="draft",
        )
    )
    products.append(
        SeedProduct(
            number=42,
            category="beds",
            style="classic",
            name="سرير مخفي",
            description="Hidden bed that must never appear in results.",
            price=Decimal(15000),
            discount_price=None,
            width_cm=Decimal(180),
            height_cm=Decimal(120),
            depth_cm=Decimal(210),
            weight_kg=Decimal(70),
            materials=("beech_wood",),
            colours=(SeedColour("brown", 2),),
            lifecycle_state="hidden",
        )
    )
    products.append(
        SeedProduct(
            number=43,
            category="chairs",
            style="modern",
            name="كرسي نفد",
            description="Published chair with no stock in any colour.",
            price=Decimal(2100),
            discount_price=None,
            width_cm=Decimal(46),
            height_cm=Decimal(88),
            depth_cm=Decimal(52),
            weight_kg=Decimal(6),
            materials=("metal", "fabric"),
            colours=(SeedColour("grey", 0), SeedColour("black", 0)),
        )
    )
    products.append(
        SeedProduct(
            number=44,
            category="wardrobes",
            style="modern",
            name="دولاب بدون مقاسات",
            description="Published wardrobe with unknown dimensions.",
            price=Decimal(12000),
            discount_price=None,
            width_cm=None,
            height_cm=None,
            depth_cm=None,
            weight_kg=None,
            materials=("mdf",),
            colours=(SeedColour("white", 2),),
        )
    )
    assert base.number == 1
    return tuple(products)


SEED_PRODUCTS: tuple[SeedProduct, ...] = _build()


def upstream_payload(product: SeedProduct, *, category_id: str, seller_id: str) -> dict:
    """The PostgREST-shaped payload the gateway would return for a seed row."""

    return {
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "price": float(product.price),
        "discount_price": None
        if product.discount_price is None
        else float(product.discount_price),
        "width": None if product.width_cm is None else float(product.width_cm),
        "height": None if product.height_cm is None else float(product.height_cm),
        "depth": None if product.depth_cm is None else float(product.depth_cm),
        "weight": None if product.weight_kg is None else float(product.weight_kg),
        "materials": [MATERIAL_TOKENS[slug] for slug in product.materials],
        "lifecycle_state": product.lifecycle_state,
        "category": {
            "id": category_id,
            "name": CATEGORY_LABELS[product.category],
            "is_active": True,
        },
        "seller": {
            "id": seller_id,
            "business_name": "Seed Seller",
            "approval_state": "approved",
        },
        "colors": [
            {
                "id": product.colour_id(index),
                "color_value": COLOUR_LABELS[colour.slug],
                "stock_quantity": colour.stock,
                "display_order": index,
            }
            for index, colour in enumerate(product.colours)
        ],
        "images": [
            {
                "id": product.image_id(0),
                "image_url": product.image_url,
                "is_primary": True,
                "display_order": 0,
                "product_color_id": None,
            }
        ],
        "enrichment_assignments": [],
    }


def _literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | Decimal):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(type(value))


def _array(values: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join(_literal(v) for v in values) + "]::text[]"


def render_seed_sql() -> str:
    lines = [
        "/*",
        "Phase 5 fake catalogue seed -- FAKE-DATA TESTING BRANCH ONLY.",
        "",
        "Inserts 44 SEED- products: 41 recommendation-eligible (40 with",
        "dimensions and one without), plus one draft, one hidden, and one",
        "published without stock; their colours; and one real category photograph",
        "each, all under the first approved seller.",
        "",
        "Rendered by tests/seed_catalogue.py; do not hand-edit. Remove with",
        "seed/phase-5-fake-catalogue-remove.sql. Never run against production.",
        "*/",
        "",
        "BEGIN;",
        "",
        "SET LOCAL lock_timeout = '5s';",
        "SET LOCAL statement_timeout = '2min';",
        "",
        "DO $seed_preflight$",
        "BEGIN",
        "    IF (",
        "        SELECT count(*) FROM public.category",
        "        WHERE name IN ("
        + ", ".join(_literal(label) for label in CATEGORY_LABELS.values())
        + ")",
        "          AND is_active",
        "    ) <> 5 THEN",
        "        RAISE EXCEPTION 'seed requires the five active bilingual categories';",
        "    END IF;",
        "    IF NOT EXISTS (",
        "        SELECT 1 FROM public.marketplace_party",
        "        WHERE approval_state = 'approved'::public.party_approval_state",
        "    ) THEN",
        "        RAISE EXCEPTION 'seed requires an approved seller';",
        "    END IF;",
        "    IF EXISTS (SELECT 1 FROM public.product WHERE sku LIKE 'SEED-%') THEN",
        "        RAISE EXCEPTION 'seed products already exist; run the remove script first';",
        "    END IF;",
        "END",
        "$seed_preflight$;",
        "",
        "INSERT INTO public.product (",
        "    id, marketplace_party_id, category_id, name, description, price,",
        "    discount_price, width_cm, height_cm, depth_cm, weight_kg, materials,",
        "    lifecycle_state, sku",
        ")",
        "SELECT",
        "    seed.id::uuid,",
        "    (",
        "        SELECT party.id FROM public.marketplace_party AS party",
        "        WHERE party.approval_state = 'approved'::public.party_approval_state",
        "        ORDER BY party.id LIMIT 1",
        "    ),",
        "    category.id,",
        "    seed.name, seed.description, seed.price, seed.discount_price,",
        "    seed.width_cm, seed.height_cm, seed.depth_cm, seed.weight_kg,",
        "    seed.materials, seed.lifecycle_state::public.product_state, seed.sku",
        "FROM (",
        "    VALUES",
    ]
    rows = []
    for product in SEED_PRODUCTS:
        rows.append(
            "        ("
            + ", ".join(
                (
                    _literal(product.id),
                    _literal(CATEGORY_LABELS[product.category]),
                    _literal(product.name),
                    _literal(product.description),
                    _literal(product.price),
                    _literal(product.discount_price),
                    _literal(product.width_cm),
                    _literal(product.height_cm),
                    _literal(product.depth_cm),
                    _literal(product.weight_kg),
                    _array(tuple(MATERIAL_TOKENS[m] for m in product.materials)),
                    _literal(product.lifecycle_state),
                    _literal(product.sku),
                )
            )
            + ")"
        )
    lines.append(",\n".join(rows))
    lines += [
        ") AS seed(",
        "    id, category_name, name, description, price, discount_price, width_cm,",
        "    height_cm, depth_cm, weight_kg, materials, lifecycle_state, sku",
        ")",
        "JOIN public.category ON category.name = seed.category_name;",
        "",
        "INSERT INTO public.product_color (",
        "    id, product_id, color_value, stock_quantity, display_order",
        ")",
        "VALUES",
    ]
    colour_rows = []
    for product in SEED_PRODUCTS:
        for index, colour in enumerate(product.colours):
            colour_rows.append(
                "    ("
                + ", ".join(
                    (
                        _literal(product.colour_id(index)) + "::uuid",
                        _literal(product.id) + "::uuid",
                        _literal(COLOUR_LABELS[colour.slug]),
                        _literal(colour.stock),
                        _literal(index),
                    )
                )
                + ")"
            )
    lines.append(",\n".join(colour_rows) + ";")
    lines += [
        "",
        "INSERT INTO public.product_image (",
        "    id, product_id, image_url, display_order, is_primary, product_color_id",
        ")",
        "VALUES",
    ]
    image_rows = [
        "    ("
        + ", ".join(
            (
                _literal(product.image_id(0)) + "::uuid",
                _literal(product.id) + "::uuid",
                _literal(product.image_url),
                "0",
                "true",
                "NULL",
            )
        )
        + ")"
        for product in SEED_PRODUCTS
    ]
    lines.append(",\n".join(image_rows) + ";")
    lines += ["", "COMMIT;", ""]
    return "\n".join(lines)


def render_remove_sql() -> str:
    return "\n".join(
        [
            "/*",
            "Remove the Phase 5 fake catalogue seed -- FAKE-DATA TESTING BRANCH ONLY.",
            "",
            "Deletes only rows whose product carries a SEED- SKU, children first.",
            "Rendered by tests/seed_catalogue.py; do not hand-edit.",
            "*/",
            "",
            "BEGIN;",
            "",
            "SET LOCAL lock_timeout = '5s';",
            "SET LOCAL statement_timeout = '2min';",
            "",
            "DELETE FROM public.product_image",
            "WHERE product_id IN (SELECT id FROM public.product WHERE sku LIKE 'SEED-%');",
            "",
            "DELETE FROM public.product_color",
            "WHERE product_id IN (SELECT id FROM public.product WHERE sku LIKE 'SEED-%');",
            "",
            "DELETE FROM public.product",
            "WHERE sku LIKE 'SEED-%';",
            "",
            "COMMIT;",
            "",
        ]
    )


def render_image_update_sql() -> str:
    """SQL that refreshes image URLs on a seed already loaded into a database.

    Re-running the insert is not an option once the rows exist, and dropping
    and reinserting the whole seed is a bigger hammer than a changed image
    warrants. This updates one column on rows that belong to SEED- products and
    touches nothing else.
    """

    rows = [
        "    ("
        + _literal(product.image_id(0))
        + "::uuid, "
        + _literal(product.image_url)
        + ")"
        for product in SEED_PRODUCTS
    ]
    return "\n".join(
        [
            "/*",
            "Refresh Phase 5 seed images -- FAKE-DATA TESTING BRANCH ONLY.",
            "",
            "Replaces the placeholder image on every SEED- product with a real",
            "category photograph. Updates one column, inserts nothing, deletes",
            "nothing, and matches only rows whose product carries a SEED- SKU.",
            "Safe to run more than once.",
            "",
            "Rendered by tests/seed_catalogue.py; do not hand-edit.",
            "*/",
            "",
            "BEGIN;",
            "",
            "SET LOCAL lock_timeout = '5s';",
            "SET LOCAL statement_timeout = '2min';",
            "",
            "DO $image_preflight$",
            "BEGIN",
            "    IF NOT EXISTS (SELECT 1 FROM public.product WHERE sku LIKE 'SEED-%') THEN",
            "        RAISE EXCEPTION 'no SEED- products found; load the seed first';",
            "    END IF;",
            "END",
            "$image_preflight$;",
            "",
            "UPDATE public.product_image AS target",
            "SET image_url = source.image_url",
            "FROM (VALUES",
            ",\n".join(rows),
            ") AS source(id, image_url)",
            "WHERE target.id = source.id",
            "  AND EXISTS (",
            "      SELECT 1 FROM public.product AS owner",
            "      WHERE owner.id = target.product_id",
            "        AND owner.sku LIKE 'SEED-%'",
            "  );",
            "",
            "COMMIT;",
            "",
        ]
    )


def as_json_fixture() -> str:
    """All seed products as the gateway would return them, for offline tests."""

    category_ids = {
        slug: f"7d000000-0000-4000-8000-{index:012d}"
        for index, slug in enumerate(CATEGORY_LABELS, start=1)
    }
    return json.dumps(
        [
            upstream_payload(
                product,
                category_id=category_ids[product.category],
                seller_id="7e000000-0000-4000-8000-000000000001",
            )
            for product in SEED_PRODUCTS
        ],
        ensure_ascii=False,
    )


if __name__ == "__main__":
    SEED_SQL_PATH.parent.mkdir(exist_ok=True)
    SEED_SQL_PATH.write_text(render_seed_sql(), encoding="utf-8", newline="\n")
    REMOVE_SQL_PATH.write_text(render_remove_sql(), encoding="utf-8", newline="\n")
    IMAGES_SQL_PATH.write_text(
        render_image_update_sql(), encoding="utf-8", newline="\n"
    )
    print(
        f"wrote {SEED_SQL_PATH.relative_to(PROJECT_ROOT)} ({len(SEED_PRODUCTS)} products)"
    )
    print(f"wrote {REMOVE_SQL_PATH.relative_to(PROJECT_ROOT)}")
    print(f"wrote {IMAGES_SQL_PATH.relative_to(PROJECT_ROOT)}")
