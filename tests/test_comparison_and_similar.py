"""Product comparison and similar products (Phase 6D), through the real gateway.

Supabase is a mock serving the Phase 5 seed and no provider exists, because
neither endpoint calls one.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.recommendations.similar import find_similar
from tests import test_rooms_endpoint as rooms
from tests.test_seed_catalogue import normalized_seed


def seed_id(suffix: int) -> str:
    return f"7a000000-0000-4000-8000-{suffix:012d}"


MODERN_SOFA = seed_id(17)  # 13,500; 220 x 95; 5 in stock
COMPACT_SOFA = seed_id(19)  # 9,900; 165 x 88; 5 in stock
DISCOUNTED_SOFA = seed_id(24)  # 15,800 discounted to 13,430; 215 x 92; 3 in stock
DRAFT_SOFA = seed_id(41)  # not published
SOLD_OUT_CHAIR = seed_id(43)  # no stock in any colour
NO_SIZE_WARDROBE = seed_id(44)  # no dimensions listed
WARDROBE = seed_id(25)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def compare(body: dict, *, authenticated: bool = True):
    async with rooms.room_client(rooms.seed_catalogue, None) as client:
        return await client.post(
            "/v1/compare",
            json=body,
            headers=rooms.auth_headers() if authenticated else {},
        )


async def similar(product_id: str, query: str = "", *, authenticated: bool = True):
    async with rooms.room_client(rooms.seed_catalogue, None) as client:
        return await client.get(
            f"/v1/catalog/products/{product_id}/similar{query}",
            headers=rooms.auth_headers() if authenticated else {},
        )


def row(payload: dict, code: str) -> dict:
    return next(r for r in payload["rows"] if r["code"] == code)


# --- comparison -----------------------------------------------------------------


@pytest.mark.anyio
async def test_three_sofas_are_compared_on_catalogue_facts() -> None:
    ids = [MODERN_SOFA, COMPACT_SOFA, DISCOUNTED_SOFA]
    response = await compare({"product_ids": ids})

    assert response.status_code == 200
    payload = response.json()
    # In the order the customer listed them, every row covering every product.
    assert [p["id"] for p in payload["products"]] == ids
    for r in payload["rows"]:
        assert [v["product_id"] for v in r["values"]] == ids

    price = row(payload, "price")
    assert [v["value"] for v in price["values"]] == ["13500", "9900", "13430"]
    assert price["highlight"] == [COMPACT_SOFA]
    assert price["highlight_rule"] == "lowest"
    assert row(payload, "discount")["highlight"] == [DISCOUNTED_SOFA]
    assert row(payload, "footprint")["highlight"] == [COMPACT_SOFA]
    # A tie is reported as a tie, not broken arbitrarily.
    assert row(payload, "stock")["highlight"] == [MODERN_SOFA, COMPACT_SOFA]
    assert row(payload, "width_cm")["highlight"] == []

    summary = {s["code"]: s["text"] for s in payload["summary"]}
    assert "3,600 EGP less" in summary["cheapest"]
    assert "smallest_footprint" in summary


@pytest.mark.anyio
async def test_a_comparison_answers_in_arabic_when_asked() -> None:
    response = await compare(
        {"product_ids": [MODERN_SOFA, COMPACT_SOFA], "language": "ar"}
    )

    payload = response.json()
    assert payload["language"] == "ar"
    assert row(payload, "price")["label"] == "السعر"
    assert row(payload, "price")["values"][1]["text"] == "9,900 جنيه"
    assert row(payload, "width_cm")["values"][0]["text"] == "220 سم"


@pytest.mark.anyio
async def test_missing_sizes_are_said_and_never_highlighted() -> None:
    response = await compare({"product_ids": [NO_SIZE_WARDROBE, WARDROBE]})

    payload = response.json()
    footprint = row(payload, "footprint")
    assert footprint["values"][0]["text"] == "Not listed"
    assert footprint["values"][0]["value"] is None
    assert footprint["highlight"] == []


@pytest.mark.anyio
@pytest.mark.parametrize("hidden", [DRAFT_SOFA, SOLD_OUT_CHAIR, seed_id(999)])
async def test_a_product_the_customer_cannot_buy_cannot_be_compared(
    hidden: str,
) -> None:
    response = await compare({"product_ids": [MODERN_SOFA, hidden]})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "product_not_found"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "ids",
    [
        [MODERN_SOFA],
        [MODERN_SOFA, MODERN_SOFA],
        [seed_id(n) for n in (17, 18, 19, 20, 21)],
        ["not-a-uuid", MODERN_SOFA],
    ],
)
async def test_unusable_comparisons_are_rejected(ids: list[str]) -> None:
    response = await compare({"product_ids": ids})

    assert response.status_code == 422


@pytest.mark.anyio
async def test_comparison_requires_authentication() -> None:
    response = await compare(
        {"product_ids": [MODERN_SOFA, COMPACT_SOFA]}, authenticated=False
    )

    assert response.status_code == 401


# --- similar products -----------------------------------------------------------


@pytest.mark.anyio
async def test_similar_products_are_real_sofas_with_their_shared_facts() -> None:
    response = await similar(MODERN_SOFA)

    assert response.status_code == 200
    payload = response.json()
    seed = {str(p.id): p for p in normalized_seed()}
    target = seed[MODERN_SOFA]
    assert 1 <= len(payload["items"]) <= 6
    for item in payload["items"]:
        product = seed[item["product"]["id"]]
        assert product.category.slug == "sofas"
        assert item["product"]["id"] not in (MODERN_SOFA, DRAFT_SOFA)
        difference = product.effective_price - target.effective_price
        assert Decimal(item["price_difference"]) == difference
        codes = [r["code"] for r in item["reasons"]]
        assert "price" in codes


@pytest.mark.anyio
async def test_similar_products_answer_in_arabic_and_honour_the_limit() -> None:
    response = await similar(MODERN_SOFA, "?limit=2&language=ar")

    payload = response.json()
    assert len(payload["items"]) == 2
    price_reasons = [
        r["text"]
        for i in payload["items"]
        for r in i["reasons"]
        if r["code"] == "price"
    ]
    assert all("جنيه" in text or "بنفس السعر" in text for text in price_reasons)


@pytest.mark.anyio
@pytest.mark.parametrize("query", ["?limit=0", "?limit=13", "?language=fr"])
async def test_unusable_similar_requests_are_rejected(query: str) -> None:
    response = await similar(MODERN_SOFA, query)

    assert response.status_code == 422


@pytest.mark.anyio
async def test_similar_to_a_hidden_product_is_not_found() -> None:
    response = await similar(DRAFT_SOFA)

    assert response.status_code == 404


def test_out_of_stock_and_other_kinds_are_never_similar() -> None:
    seed = normalized_seed()
    chair = next(p for p in seed if str(p.id) == seed_id(33))

    found = find_similar(chair, seed, limit=50)

    ids = {str(s.product.id) for s in found}
    assert SOLD_OUT_CHAIR not in ids
    assert seed_id(33) not in ids
    assert all(s.product.category.slug == chair.category.slug for s in found)
    assert [s.score for s in found] == sorted((s.score for s in found), reverse=True)


def test_a_closer_price_ranks_higher_when_nothing_else_differs() -> None:
    seed = normalized_seed()
    target = next(p for p in seed if str(p.id) == MODERN_SOFA)
    near = target.model_copy(update={"id": seed[0].id, "price": Decimal(13600)})
    near = near.model_copy(update={"effective_price": Decimal(13600)})
    far = target.model_copy(
        update={"id": seed[1].id, "effective_price": Decimal(20000)}
    )

    found = find_similar(target, [far, near])

    assert [s.product.id for s in found] == [near.id, far.id]
