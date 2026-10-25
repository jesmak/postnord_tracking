"""PostNord's API: the access token, refreshing it, and errors."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.postnord_tracking.api import PostNordAuthError, PostNordClient, PostNordError, revoke
from custom_components.postnord_tracking.const import API_KEY, CLIENT_ID, REVOKE_URL, USERINFO_URL

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
    return PostNordClient(async_get_clientsession(hass), ACCESS_TOKEN, REFRESH_TOKEN, "fi", saved.append if saved is not None else None)


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
async def test_an_expired_token_is_refreshed(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, first_status: int) -> None:
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


async def test_a_refused_refresh_token_needs_a_new_one(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(TRACKING_URL, status=401)
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    with pytest.raises(PostNordAuthError):
        await client(hass).tracking()


async def test_a_refreshed_token_that_is_refused_too_needs_a_new_one(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(TRACKING_URL, status=401)
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    with pytest.raises(PostNordAuthError):
        await client(hass).tracking()


async def test_a_gateway_that_refuses_a_fresh_token_is_no_reason_to_log_in_again(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    # Such as after PostNord changes the app's API key: a new login would be refused the same way.
    aioclient_mock.get(TRACKING_URL, status=403)
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    with pytest.raises(PostNordError) as error:
        await client(hass).tracking()
    assert not isinstance(error.value, PostNordAuthError)


@pytest.mark.parametrize("error", ["invalid_grant", "invalid_client", "unauthorized_client"])
async def test_a_refresh_token_postnord_says_is_gone_needs_a_new_login(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, error: str
) -> None:
    aioclient_mock.get(TRACKING_URL, status=401)
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": error})
    with pytest.raises(PostNordAuthError):
        await client(hass).tracking()


@pytest.mark.parametrize(
    ("token_status", "answer"), [(429, {"error": "too_many_requests"}), (400, {"error": "temporarily_unavailable"}), (403, {})]
)
async def test_a_refresh_that_fails_otherwise_is_tried_again_later(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, token_status: int, answer: dict
) -> None:
    aioclient_mock.get(TRACKING_URL, status=401)
    aioclient_mock.post(TOKEN_URL, status=token_status, json=answer)
    with pytest.raises(PostNordError) as error:
        await client(hass).tracking()
    assert not isinstance(error.value, PostNordAuthError)


@pytest.mark.parametrize("body", ["", "<html><body>Unauthorized</body></html>"])
async def test_a_refresh_refused_with_401_needs_a_new_login_whatever_its_body(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, body: str
) -> None:
    aioclient_mock.get(TRACKING_URL, status=401)
    aioclient_mock.post(TOKEN_URL, status=401, text=body)
    with pytest.raises(PostNordAuthError):
        await client(hass).tracking()


async def test_a_refresh_answered_with_a_page_says_so(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    # Such as a firewall's page: nothing about the token, so the next update tries again.
    aioclient_mock.get(TRACKING_URL, status=401)
    aioclient_mock.post(TOKEN_URL, status=400, text="<html><body>Bad request</body></html>")
    with pytest.raises(PostNordError, match="status 400, not JSON") as error:
        await client(hass).tracking()
    assert not isinstance(error.value, PostNordAuthError)


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


@pytest.mark.parametrize("error", [TimeoutError(), aiohttp.ClientConnectionError("Connection reset")], ids=["timeout", "message"])
@pytest.mark.parametrize("request_", ["tracking", "refresh"])
async def test_connection_errors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, request_: str, error: Exception) -> None:
    if request_ == "tracking":
        aioclient_mock.get(TRACKING_URL, exc=error)
    else:
        aioclient_mock.get(TRACKING_URL, status=401)
        aioclient_mock.post(TOKEN_URL, exc=error)
    with pytest.raises(PostNordError) as raised:
        await client(hass).tracking()
    purpose = " for a new access token" if request_ == "refresh" else ""
    assert str(raised.value) == f"PostNord couldn't be reached{purpose}: {str(error) or 'TimeoutError'}", "an empty message is named"


async def test_an_unexpected_response(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(TRACKING_URL, json=[1, 2, 3])
    with pytest.raises(PostNordError):
        await client(hass).tracking()


@pytest.mark.parametrize(
    "answer",
    [{"fault": "Gateway timeout"}, {"activeShipments": None, "archivedShipments": []}, {"activeShipments": []}],
)
async def test_an_answer_without_the_parcel_lists_is_no_empty_account(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, answer: dict
) -> None:
    aioclient_mock.get(TRACKING_URL, json=answer)
    with pytest.raises(PostNordError, match="without its parcel lists"):
        await client(hass).tracking()


async def test_an_error_in_the_answer_is_quoted(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(TRACKING_URL, json={"fault": "Gateway timeout"})
    with pytest.raises(PostNordError, match="fault 'Gateway timeout'"):
        await client(hass).tracking()


async def test_an_answer_that_is_not_json(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(TRACKING_URL, text="<html><body>Maintenance</body></html>")
    with pytest.raises(PostNordError, match="something other than JSON"):
        await client(hass).tracking()


async def test_the_account_comes_from_userinfo(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(USERINFO_URL, json=USERINFO)

    assert await client(hass).account() == (USERINFO["email"], USERINFO["sub"])

    [(_method, url, _data, headers)] = aioclient_mock.mock_calls
    assert "apikey" not in url.query, "the gateway key is only for the API gateway"
    assert "context" not in headers
    assert headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"


async def test_userinfo_without_an_email(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(USERINFO_URL, json={"sub": "user-1"})

    with pytest.raises(PostNordError):
        await client(hass).account()


async def test_userinfo_without_a_subject(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(USERINFO_URL, json={"email": USERINFO["email"]})

    assert await client(hass).account() == (USERINFO["email"], None)


async def test_revoking_a_login(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(REVOKE_URL, text="")

    await revoke(async_get_clientsession(hass), REFRESH_TOKEN)

    [(_method, _url, posted, _headers)] = aioclient_mock.mock_calls
    assert posted == {"token": REFRESH_TOKEN, "token_type_hint": "refresh_token", "client_id": CLIENT_ID}


async def test_a_revocation_that_fails(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(REVOKE_URL, status=400, json={"error": "unsupported_token_type"})

    with pytest.raises(PostNordError, match="unsupported_token_type"):
        await revoke(async_get_clientsession(hass), REFRESH_TOKEN)
