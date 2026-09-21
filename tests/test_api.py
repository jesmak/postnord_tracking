"""PostNord's API: the access token, refreshing it, and errors."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.postnord_tracking.api import PostNordAuthError, PostNordClient, PostNordError
from custom_components.postnord_tracking.const import API_KEY, CLIENT_ID, USERINFO_URL

from .conftest import (
    ACCESS_TOKEN,
    NEW_ACCESS_TOKEN,
    NEW_REFRESH_TOKEN,
    REFRESH_TOKEN,
    TOKEN,
    TOKEN_URL,
    TRACKING_URL,
    USERINFO,
    answers,
    tracking,
)


def client(hass: HomeAssistant, saved: list[str] | None = None) -> PostNordClient:
    return PostNordClient(
        async_get_clientsession(hass), ACCESS_TOKEN, REFRESH_TOKEN, "fi", saved.append if saved is not None else None
    )


async def test_parcels_are_fetched_with_the_token(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(TRACKING_URL, json=tracking())
    data = await client(hass).tracking()
    assert "activeShipments" in data

    [(_method, url, _data, headers)] = aioclient_mock.mock_calls
    assert url.query["summary"] == "false"
    assert url.query["apikey"] == API_KEY
    assert headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert headers["context"] == "mobileapp"


@pytest.mark.parametrize("first_status", [401, 403])
async def test_an_expired_token_is_refreshed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, first_status: int
) -> None:
    aioclient_mock.get(TRACKING_URL, side_effect=answers((first_status, None), (200, tracking())))
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    saved: list[str] = []
    postnord = client(hass, saved)

    assert "activeShipments" in await postnord.tracking()
    assert postnord.access_token == NEW_ACCESS_TOKEN
    assert saved == [NEW_ACCESS_TOKEN], "the new access token is handed over for saving"

    _expired, refresh, retry = aioclient_mock.mock_calls
    assert refresh[2] == {"grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID}
    assert retry[3]["Authorization"] == f"Bearer {NEW_ACCESS_TOKEN}"


async def test_a_rotated_refresh_token_is_kept(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(TRACKING_URL, side_effect=answers((401, None), (200, tracking())))
    aioclient_mock.post(TOKEN_URL, json={**TOKEN, "refresh_token": NEW_REFRESH_TOKEN})
    postnord = client(hass)

    await postnord.tracking()
    assert postnord.refresh_token == NEW_REFRESH_TOKEN, "the next refresh must use the rotated token"


async def test_a_refused_refresh_token_needs_a_new_one(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(TRACKING_URL, status=401)
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    with pytest.raises(PostNordAuthError):
        await client(hass).tracking()


async def test_a_refreshed_token_that_is_refused_too_needs_a_new_one(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(TRACKING_URL, status=401)
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    with pytest.raises(PostNordAuthError):
        await client(hass).tracking()


@pytest.mark.parametrize(("tracking_status", "token_status"), [(503, None), (401, 502)])
async def test_server_errors_are_not_token_problems(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, tracking_status: int, token_status: int | None
) -> None:
    aioclient_mock.get(TRACKING_URL, status=tracking_status)
    if token_status is not None:
        aioclient_mock.post(TOKEN_URL, status=token_status)
    with pytest.raises(PostNordError) as error:
        await client(hass).tracking()
    assert not isinstance(error.value, PostNordAuthError)


async def test_connection_errors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(TRACKING_URL, exc=aiohttp.ClientError("connection reset"))
    with pytest.raises(PostNordError):
        await client(hass).tracking()


async def test_an_unexpected_response(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(TRACKING_URL, json=[1, 2, 3])
    with pytest.raises(PostNordError):
        await client(hass).tracking()


async def test_the_account_email_comes_from_userinfo(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(USERINFO_URL, json=USERINFO)

    assert await client(hass).email() == USERINFO["email"]

    [(_method, url, _data, headers)] = aioclient_mock.mock_calls
    assert "apikey" not in url.query, "the gateway key is only for the API gateway"
    assert "context" not in headers
    assert headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"


async def test_userinfo_without_an_email(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(USERINFO_URL, json={"sub": "user-1"})

    with pytest.raises(PostNordError):
        await client(hass).email()
