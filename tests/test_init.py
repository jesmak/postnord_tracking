"""Setting up an account and its sensor, and token problems."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.postnord_tracking import async_migrate_entry
from custom_components.postnord_tracking.const import DOMAIN

from .conftest import ENTRY_DATA, NEW_ACCESS_TOKEN, NOW, TOKEN, TOKEN_URL, TRACKING_URL, USERNAME, answers, tracking

ENTITY_ID = "sensor.postnord_matti_meikalainen_example_com"


def account(hass: HomeAssistant, **options: object) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title=USERNAME, version=1, minor_version=2, unique_id=USERNAME, data={**ENTRY_DATA, **options})
    entry.add_to_hass(hass)
    return entry


async def test_the_sensor_lists_the_packages(hass: HomeAssistant, postnord: AiohttpClientMocker, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    entry = account(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state.state == "2026-09-16T08:30:00+00:00", "the latest change, from the parcel in transport"
    assert state.attributes["device_class"] == "timestamp"
    assert state.attributes["attribution"] == "Data provided by PostNord Group AB"
    assert [package["shipment_number"] for package in state.attributes["packages"]] == [
        "PN0002",
        "PN0001",
        "PN0006",
        "PN0003",
    ]
    assert er.async_get(hass).async_get(ENTITY_ID).unique_id == f"postnord_{USERNAME}"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_a_refreshed_access_token_is_saved(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOW)
    aioclient_mock.get(TRACKING_URL, side_effect=answers((401, None), (200, tracking())))
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    entry = account(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.data["access_token"] == NEW_ACCESS_TOKEN
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(ENTITY_ID).state == "2026-09-16T08:30:00+00:00"


async def test_a_token_that_stops_working_asks_for_a_new_one(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(TRACKING_URL, status=401)
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    entry = account(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"]["source"] == SOURCE_REAUTH


async def test_the_sensor_is_unavailable_while_postnord_is_down(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOW)
    aioclient_mock.get(TRACKING_URL, side_effect=answers((200, tracking()), (503, None)))
    entry = account(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state != STATE_UNAVAILABLE

    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


@pytest.mark.parametrize(("switch", "choice"), [(True, "code"), (False, "none"), (None, "none")])
async def test_the_pickup_switch_of_an_entry_of_1_1_becomes_a_choice(hass: HomeAssistant, switch: bool | None, choice: str) -> None:
    data = {key: value for key, value in ENTRY_DATA.items() if key != "pickup_code"}
    if switch is not None:
        data["include_pickup_details"] = switch
    entry = MockConfigEntry(domain=DOMAIN, title=USERNAME, version=1, minor_version=1, unique_id=USERNAME, data=data)
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)

    assert entry.minor_version == 2
    assert entry.data["pickup_code"] == choice
    assert "include_pickup_details" not in entry.data


async def test_an_entry_of_a_newer_version_is_refused(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title=USERNAME, version=2, minor_version=1, unique_id=USERNAME, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    assert not await async_migrate_entry(hass, entry)
