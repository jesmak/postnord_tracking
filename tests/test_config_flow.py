"""Adding an account by logging in, logging in again, and changing its settings."""

from __future__ import annotations

import base64
import hashlib
from typing import Any
from urllib.parse import parse_qs, urlparse

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.postnord_tracking.const import CLIENT_ID, DOMAIN, REDIRECT_URI, USERINFO_URL

from .conftest import (
    ENTRY_DATA,
    NEW_ACCESS_TOKEN,
    NEW_REFRESH_TOKEN,
    TOKEN_URL,
    TRACKING_URL,
    USERINFO,
    USERNAME,
    tracking,
)

CODE = "login-code"
LOGIN_TOKENS = {"access_token": NEW_ACCESS_TOKEN, "refresh_token": NEW_REFRESH_TOKEN, "expires_in": 3600}
# The address as PostNord spells it; the account's id is its lowercase form.
EMAIL = USERINFO["email"]

SETTINGS = {
    "language": "fi",
    "prioritize_undelivered": True,
    "max_shipments": 5.0,
    "stale_shipment_day_limit": 15.0,
    "completed_shipment_day_shown": 3.0,
    "include_pickup_details": False,
}
NEW_SETTINGS = {
    "language": "en",
    "prioritize_undelivered": False,
    "max_shipments": 10.0,
    "stale_shipment_day_limit": 30.0,
    "completed_shipment_day_shown": 170.0,
    "include_pickup_details": True,
}
STORED_NEW_SETTINGS = {
    "language": "en",
    "prioritize_undelivered": False,
    "max_shipments": 10,
    "stale_shipment_day_limit": 30,
    "completed_shipment_day_shown": 170,
    "include_pickup_details": True,
}
NEW_TOKENS = {"access_token": NEW_ACCESS_TOKEN, "refresh_token": NEW_REFRESH_TOKEN}


def login_params(result: dict) -> dict[str, str]:
    """The query of the login link the form shows."""
    url = result["description_placeholders"]["login_url"]
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


def redirect(result: dict, code: str = CODE) -> str:
    """The redirect the login on this form ends with, as copied from the developer tools."""
    return f'  location: "{REDIRECT_URI}?code={code}&state={login_params(result)["state"]}"\n'


def expect_login(aioclient_mock: AiohttpClientMocker, userinfo: dict | None = None) -> None:
    aioclient_mock.post(TOKEN_URL, json=LOGIN_TOKENS)
    aioclient_mock.get(USERINFO_URL, json=userinfo or USERINFO)
    aioclient_mock.get(TRACKING_URL, json=tracking())


def exchange_form(aioclient_mock: AiohttpClientMocker) -> dict[str, Any]:
    """What was posted to the token endpoint."""
    posts = [call for call in aioclient_mock.mock_calls if call[0] == "POST"]
    assert len(posts) == 1
    return posts[0][2]


def account(hass: HomeAssistant, **data: object) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title=USERNAME, version=1, unique_id=USERNAME, data={**ENTRY_DATA, **data})
    entry.add_to_hass(hass)
    return entry


async def start(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def paste(hass: HomeAssistant, result: dict, pasted: str) -> dict:
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"redirect_url": pasted})


async def test_the_login_link(hass: HomeAssistant) -> None:
    result = await start(hass)

    url = result["description_placeholders"]["login_url"]
    assert url.startswith("https://account.postnord.com/auth?")
    params = login_params(result)
    assert params["client_id"] == CLIENT_ID
    assert params["redirect_uri"] == REDIRECT_URI
    assert params["response_type"] == "code"
    assert params["code_challenge_method"] == "S256"
    assert "offline_access" in params["scope"].split()


async def test_adding_an_account(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    expect_login(aioclient_mock)
    result = await start(hass)

    result = await paste(hass, result, redirect(result))
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"
    assert result["description_placeholders"] == {"username": EMAIL}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], SETTINGS)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["data"] == {**ENTRY_DATA, "username": EMAIL, **NEW_TOKENS}
    assert result["result"].unique_id == USERNAME
    await hass.async_block_till_done()
    assert hass.states.get("sensor.postnord_matti_meikalainen_example_com") is not None


async def test_the_code_is_exchanged_with_the_verifier_of_the_link(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    expect_login(aioclient_mock)
    result = await start(hass)
    challenge = login_params(result)["code_challenge"]

    await paste(hass, result, redirect(result))

    posted = exchange_form(aioclient_mock)
    assert posted["grant_type"] == "authorization_code"
    assert posted["code"] == CODE
    assert posted["redirect_uri"] == REDIRECT_URI
    assert posted["client_id"] == CLIENT_ID
    digest = hashlib.sha256(posted["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).decode().rstrip("=") == challenge


async def test_a_paste_without_a_code(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    result = await start(hass)

    result = await paste(hass, result, "https://account.postnord.com/auth?client_id=x")

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"redirect_url": "no_code"}
    assert aioclient_mock.call_count == 0


async def test_the_redirect_of_another_login(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    result = await start(hass)

    result = await paste(hass, result, f"{REDIRECT_URI}?code={CODE}&state=other")

    assert result["errors"] == {"redirect_url": "wrong_state"}
    assert aioclient_mock.call_count == 0


async def test_an_expired_code(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    result = await start(hass)
    link = result["description_placeholders"]["login_url"]

    result = await paste(hass, result, redirect(result))

    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}
    # The same link is offered again, so logging in with it again works.
    assert result["description_placeholders"]["login_url"] == link


async def test_postnord_cannot_be_reached(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(TOKEN_URL, json=LOGIN_TOKENS)
    aioclient_mock.get(USERINFO_URL, status=500)
    result = await start(hass)

    result = await paste(hass, result, redirect(result))

    assert result["errors"] == {"base": "cannot_connect"}


async def test_an_account_is_added_only_once(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    expect_login(aioclient_mock)
    account(hass)
    result = await start(hass)

    result = await paste(hass, result, redirect(result))

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_logging_in_again_when_the_login_stops_working(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    expect_login(aioclient_mock)
    entry = account(hass, access_token="expired", refresh_token="expired")

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await paste(hass, result, redirect(result))
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    # The username stays as it was: the entities' ids are built from it.
    assert entry.data == {**ENTRY_DATA, **NEW_TOKENS}


async def test_logging_in_again_as_someone_else(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    expect_login(aioclient_mock, {"email": "someone.else@example.com"})
    entry = account(hass, access_token="expired", refresh_token="expired")

    result = await entry.start_reauth_flow(hass)
    result = await paste(hass, result, redirect(result))

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "wrong_account"}
    assert entry.data["refresh_token"] == "expired"


async def start_reconfigure(hass: HomeAssistant, entry: MockConfigEntry, choice: str) -> dict:
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["reconfigure_settings", "reconfigure_login"]
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": choice})


async def test_changing_the_settings(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(TRACKING_URL, json=tracking())
    entry = account(hass)

    result = await start_reconfigure(hass, entry, "reconfigure_settings")
    assert result["step_id"] == "reconfigure_settings"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], NEW_SETTINGS)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {**ENTRY_DATA, **STORED_NEW_SETTINGS}


async def test_logging_in_again_from_reconfigure(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    expect_login(aioclient_mock)
    entry = account(hass)

    result = await start_reconfigure(hass, entry, "reconfigure_login")
    assert result["step_id"] == "reconfigure_login"
    result = await paste(hass, result, redirect(result))
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {**ENTRY_DATA, **NEW_TOKENS}
