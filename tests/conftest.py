"""Shared fixtures: an account, and PostNord's API with sample parcels."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker, AiohttpClientMockResponse

from custom_components.postnord_tracking.const import API_BASE_URL, PATH_TRACKING, TOKEN_URL

USERNAME = "matti.meikalainen@example.com"
ACCESS_TOKEN = "access-token"
REFRESH_TOKEN = "refresh-token"
NEW_ACCESS_TOKEN = "new-access-token"
NEW_REFRESH_TOKEN = "new-refresh-token"

ENTRY_DATA = {
    "username": USERNAME,
    "access_token": ACCESS_TOKEN,
    "refresh_token": REFRESH_TOKEN,
    "language": "fi",
    "prioritize_undelivered": True,
    "max_shipments": 5,
    "stale_shipment_day_limit": 15,
    "completed_shipment_day_shown": 3,
    "include_pickup_details": False,
}

NOW = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)

TRACKING_URL = API_BASE_URL + PATH_TRACKING
TOKEN = {"access_token": NEW_ACCESS_TOKEN, "expires_in": 3600, "id_token": "id"}
# OpenID userinfo of the account, trimmed to what the integration reads.
USERINFO = {"sub": "user-1", "email": "Matti.Meikalainen@example.com", "email_verified": True}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Lets Home Assistant load integrations from custom_components/."""


def shipment(
    shipment_id: str,
    status: str,
    event_time: str | None = None,
    *,
    event: str = "Lähetys on noudettavissa",
    delivery_date: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """A parcel shaped like PostNord's, with made-up details. Times are ISO 8601 in UTC."""
    item: dict[str, Any] = {
        "itemId": f"{shipment_id}-1",
        "status": status,
        "statusText": {"header": event, "body": event},
    }
    if event_time is not None:
        item["events"] = [
            {"eventDescription": event, "eventTime": event_time, "status": status, "location": {"city": "Tampere"}}
        ]
    data: dict[str, Any] = {
        "shipmentId": shipment_id,
        "status": status,
        "consignor": {"name": "Verkkokauppa.com", "address": {"city": "Stockholm", "countryCode": "SE"}},
        "consignee": {"address": {"city": "Tampere", "postCode": "33100", "countryCode": "FI"}},
        "userData": {"dateAdded": "2026-09-14T06:00:00Z", "direction": "incoming"},
        "items": [item],
    }
    if delivery_date is not None:
        data["deliveryDate"] = delivery_date
    data.update(extra)
    return data


# Undelivered parcels are "active", completed ones "archived", as PostNord returns them.
ACTIVE = [
    # Ready for pickup since yesterday.
    shipment("PN0001", "AVAILABLE_FOR_DELIVERY", "2026-09-15T10:00:00Z"),
    # In transport: the latest change of all.
    shipment("PN0002", "EN_ROUTE", "2026-09-16T08:30:00Z", event="Lähetys on kuljetuksessa"),
    # Stuck in transport for weeks: hidden as stale.
    shipment("PN0005", "EN_ROUTE", "2026-08-20T09:00:00Z", event="Lähetys on kuljetuksessa"),
    # No time at all (no events, no dates): skipped.
    {**shipment("PN0007", "CREATED"), "userData": {}},
]
ARCHIVED = [
    # Delivered two days ago.
    shipment("PN0003", "DELIVERED", "2026-09-14T09:00:00Z", event="Lähetys on toimitettu"),
    # Delivered six days ago: hidden.
    shipment("PN0004", "DELIVERED", "2026-09-10T09:00:00Z", event="Lähetys on toimitettu"),
    # Delivered this morning, without events, from the delivery date.
    shipment("PN0006", "DELIVERED", delivery_date="2026-09-16T05:00:00Z"),
]


def tracking(active: list | None = None, archived: list | None = None) -> dict[str, Any]:
    return {
        "activeShipments": ACTIVE if active is None else active,
        "archivedShipments": ARCHIVED if archived is None else archived,
        "deletedShipments": [],
        "lastModifiedDate": "2026-09-16T09:00:00Z",
    }


def answers(*responses: tuple[int, Any]) -> Callable[..., Awaitable[AiohttpClientMockResponse]]:
    """Answers with the given (status, JSON) responses in turn, repeating the last one."""
    remaining = list(responses)

    async def answer(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        status, body = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return AiohttpClientMockResponse(method, url, status=status, json=body)

    return answer


@pytest.fixture
def postnord(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """PostNord's API accepting the token."""
    aioclient_mock.get(TRACKING_URL, json=tracking())
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    return aioclient_mock
