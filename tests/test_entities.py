"""The counts of an account's packages, and the events its packages fire."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker, AiohttpClientMockResponse

from custom_components.postnord_tracking.const import DOMAIN

from .conftest import ENTRY_DATA, NOW, TOKEN_URL, TRACKING_URL, USERNAME, shipment, tracking

EVENT_ENTITY = "event.postnord_matti_meikalainen_example_com_package"
ON_THE_WAY = "sensor.postnord_matti_meikalainen_example_com_packages_on_the_way"
READY = "sensor.postnord_matti_meikalainen_example_com_packages_ready_for_pickup"


async def answer(active: list[dict[str, Any]]) -> AiohttpClientMockResponse:
    """PostNord's answer, read afresh each time so a test can change the parcels."""
    return AiohttpClientMockResponse("get", TRACKING_URL, json=tracking(active=list(active), archived=[]))


def account(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title=USERNAME, version=1, minor_version=2, unique_id=USERNAME, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    return entry


async def set_up(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> MockConfigEntry:
    freezer.move_to(NOW)
    entry = account(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def test_the_counts_of_the_packages(hass: HomeAssistant, postnord: AiohttpClientMocker, freezer: FrozenDateTimeFactory) -> None:
    await set_up(hass, freezer)

    assert hass.states.get(ON_THE_WAY).state == "2", "ready for pickup and in transport"
    assert hass.states.get(ON_THE_WAY).attributes["state_class"] == "measurement"
    assert hass.states.get(READY).state == "1"
    registry = er.async_get(hass)
    assert registry.async_get(ON_THE_WAY).unique_id == f"postnord_{USERNAME}_on_the_way"
    assert registry.async_get(READY).unique_id == f"postnord_{USERNAME}_ready_for_pickup"


async def test_the_packages_already_there_are_not_events(
    hass: HomeAssistant, postnord: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    await set_up(hass, freezer)

    state = hass.states.get(EVENT_ENTITY)
    assert state.state == "unknown", "what was already there when Home Assistant started has not just happened"
    assert set(state.attributes["event_types"]) == {
        "new_package",
        "moved",
        "ready_for_pickup",
        "delivered",
        "returned",
    }


async def test_a_package_becoming_ready_for_pickup_fires_an_event(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    moving = shipment("PN0100", "EN_ROUTE", "2026-09-16T08:30:00Z", event="Lähetys on kuljetuksessa")
    arrived = shipment("PN0100", "AVAILABLE_FOR_DELIVERY", "2026-09-16T11:30:00Z")
    parcels = [moving]
    aioclient_mock.post(TOKEN_URL, json={"access_token": "t"})
    aioclient_mock.get(TRACKING_URL, side_effect=lambda *_: answer(parcels))

    await set_up(hass, freezer)
    assert hass.states.get(EVENT_ENTITY).state == "unknown"

    parcels[:] = [arrived]
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(EVENT_ENTITY)
    assert state.attributes["event_type"] == "ready_for_pickup"
    assert state.attributes["shipment_number"] == "PN0100"
    assert state.attributes["source"] == "PostNord"
    assert hass.states.get(READY).state == "1"


async def test_every_change_of_one_update_fires_its_own_event(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    before = [
        shipment("PN0201", "EN_ROUTE", "2026-09-16T08:30:00Z", event="Lähetys on kuljetuksessa"),
        shipment("PN0202", "EN_ROUTE", "2026-09-16T08:40:00Z", event="Lähetys on kuljetuksessa"),
    ]
    after = [
        shipment("PN0201", "AVAILABLE_FOR_DELIVERY", "2026-09-16T11:30:00Z"),
        shipment("PN0202", "DELIVERED", "2026-09-16T11:31:00Z", event="Lähetys on toimitettu"),
    ]
    parcels = list(before)
    aioclient_mock.post(TOKEN_URL, json={"access_token": "t"})
    aioclient_mock.get(TRACKING_URL, side_effect=lambda *_: answer(parcels))
    await set_up(hass, freezer)

    seen: list[str] = []
    hass.bus.async_listen(
        "state_changed",
        lambda call: (
            seen.append(call.data["new_state"].attributes.get("event_type"))
            if call.data["entity_id"] == EVENT_ENTITY and call.data["new_state"]
            else None
        ),
    )

    parcels[:] = after
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert seen == ["ready_for_pickup", "delivered"], "one event for each package that changed"


async def failure(method: str, url: str) -> AiohttpClientMockResponse:
    return AiohttpClientMockResponse(method, url, status=503)


async def test_an_event_after_a_failed_update_does_not_come_from_unavailable(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    current = [shipment("PN0500", "EN_ROUTE", "2026-09-16T08:30:00Z", event="Lähetys on kuljetuksessa")]
    down = False
    aioclient_mock.post(TOKEN_URL, json={"access_token": "t"})
    aioclient_mock.get(TRACKING_URL, side_effect=lambda *_: failure("get", TRACKING_URL) if down else answer(current))
    await set_up(hass, freezer)

    down = True
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(EVENT_ENTITY).state == "unavailable"

    writes: list[tuple[str, str | None]] = []
    hass.bus.async_listen(
        "state_changed",
        lambda call: (
            writes.append((call.data["old_state"].state, call.data["new_state"].attributes.get("event_type")))
            if call.data["entity_id"] == EVENT_ENTITY
            else None
        ),
    )
    down = False
    current[:] = [shipment("PN0500", "AVAILABLE_FOR_DELIVERY", "2026-09-16T11:30:00Z")]
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    # An automation leaves out a change from unavailable, as the entity coming back, so the event must not be one.
    [(before, _)] = [write for write in writes if write[1] == "ready_for_pickup"]
    assert before != "unavailable"


def event_types(hass: HomeAssistant) -> list[str]:
    """The event types the event entity writes from now on."""
    seen: list[str] = []
    hass.bus.async_listen(
        "state_changed",
        lambda call: (
            seen.append(call.data["new_state"].attributes.get("event_type"))
            if call.data["entity_id"] == EVENT_ENTITY and call.data["new_state"]
            else None
        ),
    )
    return seen


async def next_update(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_a_package_missing_from_one_answer_is_not_new_when_it_comes_back(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    both = [
        shipment("PN0301", "EN_ROUTE", "2026-09-16T08:30:00Z", event="Lähetys on kuljetuksessa"),
        shipment("PN0302", "EN_ROUTE", "2026-09-16T08:40:00Z", event="Lähetys on kuljetuksessa"),
    ]
    parcels = list(both)
    aioclient_mock.post(TOKEN_URL, json={"access_token": "t"})
    aioclient_mock.get(TRACKING_URL, side_effect=lambda *_: answer(parcels))
    await set_up(hass, freezer)
    seen = event_types(hass)

    parcels[:] = both[:1]
    await next_update(hass, freezer)
    parcels[:] = both
    await next_update(hass, freezer)

    assert seen == [], "nothing happened to the packages"


async def test_an_answer_without_its_parcel_lists_fires_nothing_after_it(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    parcels = [shipment("PN0401", "EN_ROUTE", "2026-09-16T08:30:00Z", event="Lähetys on kuljetuksessa")]
    broken = False

    async def reply(*_: Any) -> AiohttpClientMockResponse:
        if broken:
            return AiohttpClientMockResponse("get", TRACKING_URL, json={"fault": "Gateway timeout"})
        return await answer(parcels)

    aioclient_mock.post(TOKEN_URL, json={"access_token": "t"})
    aioclient_mock.get(TRACKING_URL, side_effect=reply)
    await set_up(hass, freezer)
    seen = event_types(hass)

    broken = True
    await next_update(hass, freezer)
    assert hass.states.get(ON_THE_WAY).state == "unavailable", "a broken answer is a failed update, not an empty account"
    broken = False
    await next_update(hass, freezer)

    assert "new_package" not in seen


async def test_a_package_first_seen_at_its_pickup_point_fires_both_events(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    parcels: list[dict[str, Any]] = []
    aioclient_mock.post(TOKEN_URL, json={"access_token": "t"})
    aioclient_mock.get(TRACKING_URL, side_effect=lambda *_: answer(parcels))
    await set_up(hass, freezer)
    seen = event_types(hass)

    parcels[:] = [shipment("PN0501", "AVAILABLE_FOR_DELIVERY", "2026-09-16T11:30:00Z")]
    await next_update(hass, freezer)

    assert [event for event in seen if event] == ["new_package", "ready_for_pickup"]
