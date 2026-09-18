"""POST /v1/cart through the real gateways, against a mock Supabase."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import SecretStr

from app.auth.dependencies import get_auth_gateway
from app.auth.gateway import AuthenticationGateway
from app.auth.models import AuthenticatedUser
from app.cart.gateway import SupabaseCartCreator, SupabaseCustomerCartReader
from app.cart.router import get_cart_creator, get_cart_reader
from app.config import Settings
from app.main import app
from tests.test_catalog import TEST_ACCESS_TOKEN, TEST_USER_ID, build_test_settings

SECRET = "sb_secret_test_value_never_real"
PROFILE = "5c000000-0000-4000-8000-000000000001"
CART = "6c000000-0000-4000-8000-000000000001"


class VerifiedAuthGateway:
    async def authenticate(self, access_token: str) -> AuthenticatedUser:
        assert access_token == TEST_ACCESS_TOKEN
        return AuthenticatedUser(user_id=TEST_USER_ID)


def settings_with_secret() -> Settings:
    return build_test_settings().model_copy(
        update={"supabase_secret_key": SecretStr(SECRET)}
    )


class FakeSupabase:
    """Records every request; answers like PostgREST."""

    def __init__(self, *, profile=True, cart=False, insert_status=201) -> None:
        self.profile = profile
        self.cart = cart
        self.insert_status = insert_status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path.endswith("/customer_profile"):
            return httpx.Response(200, json=[{"id": PROFILE}] if self.profile else [])
        if request.method == "GET" and path.endswith("/cart"):
            return httpx.Response(200, json=[{"id": CART}] if self.cart else [])
        if request.method == "POST" and path.endswith("/cart"):
            if self.insert_status == 409:
                self.cart = True
                return httpx.Response(409, json={"code": "23505"})
            if self.insert_status != 201:
                return httpx.Response(self.insert_status, json={})
            self.cart = True
            return httpx.Response(201, json=[{"id": CART}])
        raise AssertionError(f"unexpected {request.method} {path}")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@asynccontextmanager
async def cart_client(
    supabase: Callable[[httpx.Request], httpx.Response], *, with_secret: bool = True
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(supabase)) as up:
        reader = SupabaseCustomerCartReader(client=up, settings=build_test_settings())
        creator = (
            SupabaseCartCreator(client=up, settings=settings_with_secret())
            if with_secret
            else None
        )

        async def auth() -> AuthenticationGateway:
            return VerifiedAuthGateway()

        async def get_reader():
            return reader

        async def get_creator():
            return creator

        app.dependency_overrides[get_auth_gateway] = auth
        app.dependency_overrides[get_cart_reader] = get_reader
        app.dependency_overrides[get_cart_creator] = get_creator
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                yield client
        finally:
            for dependency in (get_auth_gateway, get_cart_reader, get_cart_creator):
                app.dependency_overrides.pop(dependency, None)


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"}


@pytest.mark.anyio
async def test_the_first_call_creates_the_cart_with_the_secret_key_only_there() -> None:
    supabase = FakeSupabase()

    async with cart_client(supabase) as client:
        response = await client.post("/v1/cart", headers=auth())

    assert response.status_code == 200
    assert response.json() == {"cart_id": CART, "created": True}

    reads = [r for r in supabase.requests if r.method == "GET"]
    (insert,) = [r for r in supabase.requests if r.method == "POST"]
    # Reads run as the customer: their token, never the secret key.
    for read in reads:
        assert read.headers["authorization"] == f"Bearer {TEST_ACCESS_TOKEN}"
        assert SECRET not in str(read.headers)
    # The profile is found by the verified user id, not by anything sent.
    assert reads[0].url.params["user_id"] == f"eq.{TEST_USER_ID}"
    # The insert is the one privileged call: secret key, no user token, and a
    # body holding nothing but the profile id the customer's own read returned.
    assert insert.headers["apikey"] == SECRET
    assert "authorization" not in insert.headers
    assert json.loads(insert.content) == {"customer_profile_id": PROFILE}


@pytest.mark.anyio
async def test_an_existing_cart_is_returned_without_touching_the_secret_key() -> None:
    supabase = FakeSupabase(cart=True)

    async with cart_client(supabase) as client:
        response = await client.post("/v1/cart", headers=auth())

    assert response.json() == {"cart_id": CART, "created": False}
    assert all(r.method == "GET" for r in supabase.requests)


@pytest.mark.anyio
async def test_a_race_is_resolved_by_reading_the_cart_back_as_the_user() -> None:
    supabase = FakeSupabase(insert_status=409)

    async with cart_client(supabase) as client:
        response = await client.post("/v1/cart", headers=auth())

    assert response.status_code == 200
    assert response.json() == {"cart_id": CART, "created": False}
    assert supabase.requests[-1].method == "GET"


@pytest.mark.anyio
async def test_an_account_without_a_customer_profile_gets_no_cart() -> None:
    supabase = FakeSupabase(profile=False)

    async with cart_client(supabase) as client:
        response = await client.post("/v1/cart", headers=auth())

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "customer_profile_required"
    assert all(r.method == "GET" for r in supabase.requests)


@pytest.mark.anyio
async def test_without_a_secret_key_an_existing_cart_still_works() -> None:
    async with cart_client(FakeSupabase(cart=True), with_secret=False) as client:
        response = await client.post("/v1/cart", headers=auth())

    assert response.status_code == 200


@pytest.mark.anyio
async def test_without_a_secret_key_creation_is_refused_cleanly() -> None:
    supabase = FakeSupabase()

    async with cart_client(supabase, with_secret=False) as client:
        response = await client.post("/v1/cart", headers=auth())

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "cart_unavailable"
    assert all(r.method == "GET" for r in supabase.requests)


@pytest.mark.anyio
async def test_the_cart_requires_sign_in() -> None:
    supabase = FakeSupabase()

    async with cart_client(supabase) as client:
        response = await client.post("/v1/cart")

    assert response.status_code == 401
    assert supabase.requests == []


@pytest.mark.anyio
@pytest.mark.parametrize(("upstream", "status"), [(500, 503), (401, 502)])
async def test_supabase_failures_are_mapped_and_reveal_nothing(
    upstream: int, status: int
) -> None:
    supabase = FakeSupabase(insert_status=upstream)

    async with cart_client(supabase) as client:
        response = await client.post("/v1/cart", headers=auth())

    assert response.status_code == status
    assert SECRET not in response.text


def test_the_creator_never_shows_its_key() -> None:
    creator = SupabaseCartCreator(
        client=httpx.AsyncClient(), settings=settings_with_secret()
    )

    assert SECRET not in repr(creator)
    assert SECRET not in str(vars(creator))
