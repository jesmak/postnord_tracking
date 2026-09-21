"""Turning an account's parcels into the sensor's package list.

The packages are in the format package-tracker-card reads, which other tracking integrations
write too, so the card can list them together. PostNord returns active and archived
parcels in one response, so recently delivered ones are shown as history.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

from homeassistant.util import dt as dt_util

from .const import (
    CONF_COMPLETED_SHIPMENT_DAYS_SHOWN,
    CONF_INCLUDE_PICKUP_DETAILS,
    CONF_MAX_SHIPMENTS,
    CONF_PRIORITIZE_UNDELIVERED,
    CONF_STALE_SHIPMENT_DAY_LIMIT,
    DEFAULT_COMPLETED_SHIPMENT_DAYS_SHOWN,
    DEFAULT_INCLUDE_PICKUP_DETAILS,
    DEFAULT_MAX_SHIPMENTS,
    DEFAULT_PRIORITIZE_UNDELIVERED,
    DEFAULT_STALE_SHIPMENT_DAY_LIMIT,
    TRACKING_URL,
)

# Package statuses, as package-tracker-card shows them.
STATUS_DELIVERED = 0
STATUS_WAITING = 1
STATUS_RECEIVED = 2
STATUS_IN_TRANSPORT = 3
STATUS_IN_DELIVERY = 4
STATUS_READY_FOR_PICKUP = 5
STATUS_RETURNED = 6
STATUS_UNKNOWN = 7

# PostNord's status strings onto the shared statuses. AVAILABLE_FOR_DELIVERY is mapped to ready
# for pickup on the strength of the archived data alone; confirm against an active parcel at a
# locker before trusting it (it may mean out-for-home-delivery in some cases). See NOTES.md.
STATUS_MAP = {
    "CREATED": STATUS_WAITING,
    "INFORMED": STATUS_WAITING,
    "EN_ROUTE": STATUS_IN_TRANSPORT,
    "DELAYED": STATUS_IN_TRANSPORT,
    "AVAILABLE_FOR_DELIVERY": STATUS_READY_FOR_PICKUP,
    "DELIVERED": STATUS_DELIVERED,
    "RETURNED": STATUS_RETURNED,
    "DELIVERY_REFUSED": STATUS_RETURNED,
    "DELIVERY_IMPOSSIBLE": STATUS_UNKNOWN,
    "OTHER": STATUS_UNKNOWN,
}

# The statuses a package is done at, for the recency buckets and the counts.
COMPLETED_STATUSES = (STATUS_DELIVERED, STATUS_RETURNED)


@dataclass(frozen=True)
class PackageSettings:
    prioritize_undelivered: bool
    max_shipments: int
    # Undelivered packages whose latest event is older are hidden: some stay in delivery for good.
    stale_shipment_day_limit: int
    completed_shipment_days_shown: int
    # The pickup point and the code that collects the package, which not everyone wants on a dashboard.
    include_pickup_details: bool

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> PackageSettings:
        return cls(
            prioritize_undelivered=bool(data.get(CONF_PRIORITIZE_UNDELIVERED, DEFAULT_PRIORITIZE_UNDELIVERED)),
            max_shipments=int(data.get(CONF_MAX_SHIPMENTS, DEFAULT_MAX_SHIPMENTS)),
            stale_shipment_day_limit=int(data.get(CONF_STALE_SHIPMENT_DAY_LIMIT, DEFAULT_STALE_SHIPMENT_DAY_LIMIT)),
            completed_shipment_days_shown=int(
                data.get(CONF_COMPLETED_SHIPMENT_DAYS_SHOWN, DEFAULT_COMPLETED_SHIPMENT_DAYS_SHOWN)
            ),
            include_pickup_details=bool(data.get(CONF_INCLUDE_PICKUP_DETAILS, DEFAULT_INCLUDE_PICKUP_DETAILS)),
        )


@dataclass(frozen=True)
class Packages:
    # When a shipment of the account last changed, hidden ones included. None when there are none.
    latest_change: datetime | None
    packages: list[dict[str, Any]]


def map_status(raw_status: Any) -> int:
    return STATUS_MAP.get(str(raw_status or "").upper(), STATUS_UNKNOWN)


def build_packages(tracking: Mapping[str, Any], settings: PackageSettings, now: datetime) -> Packages:
    """The packages to list: active ones that aren't stale and recently completed ones, newest first.

    PostNord's response splits parcels into active and archived; both are shown, so delivered
    history appears for a few days like the active ones do.
    """
    shipments: list[Mapping[str, Any]] = []
    for bucket in ("activeShipments", "archivedShipments"):
        found = tracking.get(bucket)
        if isinstance(found, list):
            shipments.extend(item for item in found if isinstance(item, Mapping))

    latest_change: datetime | None = None
    undelivered: list[tuple[datetime, dict[str, Any]]] = []
    completed: list[tuple[datetime, dict[str, Any]]] = []

    for shipment in shipments:
        changed = status_change_time(shipment)
        if changed is None:
            continue
        if latest_change is None or changed > latest_change:
            latest_change = changed

        built = package(shipment, changed, settings)
        status = built["status"]
        age_days = (now - changed).days
        if status not in COMPLETED_STATUSES and age_days <= settings.stale_shipment_day_limit:
            undelivered.append((changed, built))
        elif status in COMPLETED_STATUSES and age_days <= settings.completed_shipment_days_shown:
            completed.append((changed, built))

    undelivered.sort(key=change_time, reverse=True)
    completed.sort(key=change_time, reverse=True)
    ordered = undelivered + completed
    if not settings.prioritize_undelivered:
        ordered.sort(key=change_time, reverse=True)
    return Packages(latest_change, [item for _, item in ordered[: settings.max_shipments]])


def change_time(item: tuple[datetime, dict[str, Any]]) -> datetime:
    return item[0]


def first_item(shipment: Mapping[str, Any]) -> Mapping[str, Any]:
    items = shipment.get("items")
    if isinstance(items, list) and items and isinstance(items[0], Mapping):
        return items[0]
    return {}


def latest_event(item: Mapping[str, Any]) -> Mapping[str, Any]:
    """The newest tracking event of an item, by its time."""
    events = item.get("events")
    if not isinstance(events, list):
        return {}
    dated = [(parse_time(event.get("eventTime")), event) for event in events if isinstance(event, Mapping)]
    dated = [(time, event) for time, event in dated if time is not None]
    if not dated:
        return next((event for event in events if isinstance(event, Mapping)), {})
    return max(dated, key=lambda pair: pair[0])[1]


def status_change_time(shipment: Mapping[str, Any]) -> datetime | None:
    """When the shipment last changed: its newest event, else its delivery, else when it was added."""
    item = first_item(shipment)
    event_time = parse_time(latest_event(item).get("eventTime"))
    if event_time is not None:
        return event_time
    user_data = shipment.get("userData") if isinstance(shipment.get("userData"), Mapping) else {}
    for value in (shipment.get("deliveryDate"), item.get("returnDate"), user_data.get("dateAdded")):
        parsed = parse_time(value)
        if parsed is not None:
            return parsed
    return None


def package(shipment: Mapping[str, Any], changed: datetime, settings: PackageSettings) -> dict[str, Any]:
    item = first_item(shipment)
    event = latest_event(item)
    consignor = address_of(shipment.get("consignor"))
    consignee = address_of(shipment.get("consignee"))
    user_data = shipment.get("userData") if isinstance(shipment.get("userData"), Mapping) else {}
    raw_status = item.get("status") or shipment.get("status")
    point = shipment.get("destinationDeliveryPoint")
    point = point if isinstance(point, Mapping) else {}
    location = event.get("location") if isinstance(event.get("location"), Mapping) else {}
    shipment_number = shipment.get("shipmentId") or item.get("itemId")
    return {
        "origin": name_of(shipment.get("consignor")),
        "origin_city": consignor.get("city"),
        "destination": point.get("name") if point else None,
        "destination_city": consignee.get("city"),
        "shipment_number": shipment_number,
        "shipment_date": iso(parse_time(user_data.get("dateAdded"))),
        "status": map_status(raw_status),
        "raw_status": raw_status,
        "latest_event": event.get("eventDescription") or text_of(item.get("statusText")),
        "latest_event_city": location.get("city") or location.get("locationName"),
        "latest_event_country": consignee.get("countryCode"),
        "latest_event_date": changed.isoformat(),
        # Only on active parcels; absent (None) on delivered ones. Field names are tentative
        # until an active parcel is captured — see NOTES.md.
        "estimated_delivery": iso(
            parse_time(shipment.get("estimatedTimeOfArrival") or shipment.get("publicTimeOfArrival"))
        ),
        "pickup_deadline": None,
        "weight": number(measure(item.get("weight"))),
        "package_count": item_count(shipment),
        "pickup_point": pickup_point(point, consignee) if settings.include_pickup_details else None,
        "pickup_code": pickup_code(shipment) if settings.include_pickup_details else None,
        "source": "PostNord",
        "tracking_url": tracking_url(shipment_number),
    }


def item_count(shipment: Mapping[str, Any]) -> int | None:
    items = shipment.get("items")
    return len(items) if isinstance(items, list) and items else None


def address_of(party: Any) -> Mapping[str, Any]:
    if isinstance(party, Mapping) and isinstance(party.get("address"), Mapping):
        return party["address"]
    return {}


def name_of(party: Any) -> str | None:
    return party.get("name") if isinstance(party, Mapping) else None


def text_of(status_text: Any) -> str | None:
    """The human-readable status line PostNord gives, header preferred over body."""
    if isinstance(status_text, Mapping):
        return status_text.get("header") or status_text.get("body")
    return None


def measure(value: Any) -> Any:
    """The value of a {unit, value} measure, such as weight."""
    return value.get("value") if isinstance(value, Mapping) else value


def pickup_point(point: Mapping[str, Any], consignee: Mapping[str, Any]) -> dict[str, Any] | None:
    """Where the package is picked up. Only active parcels carry a destinationDeliveryPoint;
    the field names are tentative until one is captured (see NOTES.md), so read defensively."""
    address = point.get("address") if isinstance(point.get("address"), Mapping) else point
    found = {
        "name": point.get("name"),
        "street": address.get("street") or address.get("streetName"),
        "postal_code": address.get("postCode") or address.get("postalCode"),
        "city": address.get("city") or consignee.get("city"),
        "type": point.get("type"),
        "available": point.get("openingHours") or None,
    }
    return found if any(value for value in found.values()) else None


def pickup_code(shipment: Mapping[str, Any]) -> str | None:
    """The code that collects the package. PostNord serves it behind a strong-auth (levelled-up)
    token via a separate call, so it is not in this response yet — left for a later version."""
    code = shipment.get("collectCode")
    return str(code) if code else None


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_time(value: Any) -> datetime | None:
    """A PostNord time, ISO 8601 with a zone or a trailing Z."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt_util.UTC)
    return parsed


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def tracking_url(shipment_number: Any) -> str | None:
    """The carrier's own tracking page for the package."""
    return TRACKING_URL.format(number=quote(str(shipment_number), safe="")) if shipment_number else None
