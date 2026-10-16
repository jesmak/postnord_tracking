"""Turning an account's parcels into the sensor's package list.

The packages are in the format package-tracker-card reads, which other tracking integrations
write too, so the card can list them together. PostNord returns active and archived
parcels in one response, so recently delivered ones are shown as history.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

from homeassistant.util import dt as dt_util

from .const import (
    CONF_COMPLETED_SHIPMENT_DAYS_SHOWN,
    CONF_MAX_OUTGOING_SHIPMENTS,
    CONF_MAX_SHIPMENTS,
    CONF_PICKUP_CODE,
    CONF_PRIORITIZE_UNDELIVERED,
    CONF_STALE_SHIPMENT_DAY_LIMIT,
    DEFAULT_COMPLETED_SHIPMENT_DAYS_SHOWN,
    DEFAULT_MAX_OUTGOING_SHIPMENTS,
    DEFAULT_MAX_SHIPMENTS,
    DEFAULT_PICKUP_CODE,
    DEFAULT_PRIORITIZE_UNDELIVERED,
    DEFAULT_STALE_SHIPMENT_DAY_LIMIT,
    PICKUP_CODE_CODE,
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
# locker before trusting it (it may mean out-for-home-delivery in some cases).
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

# Which way a package goes, as package-tracker-card reads it. None is not known, and is taken as incoming.
DIRECTION_INCOMING = "incoming"
DIRECTION_OUTGOING = "outgoing"
# PostNord's userData.direction, seen live in capitals (INCOMING). Compared without case.
DIRECTION_MAP = {"INCOMING": DIRECTION_INCOMING, "OUTGOING": DIRECTION_OUTGOING}

# The statuses a package is done at, for the recency buckets and the counts.
COMPLETED_STATUSES = (STATUS_DELIVERED, STATUS_RETURNED)


@dataclass(frozen=True)
class PackageSettings:
    prioritize_undelivered: bool
    # The most incoming and sent packages listed. 0 leaves that direction out of the list, the counts and the events.
    max_shipments: int
    max_outgoing_shipments: int
    # Undelivered packages whose latest event is older are hidden: some stay in delivery for good.
    stale_shipment_day_limit: int
    completed_shipment_days_shown: int
    # none or code: the code collects the package, which not everyone wants on a dashboard. The pickup point itself is
    # always included.
    pickup_code: str

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> PackageSettings:
        return cls(
            prioritize_undelivered=bool(data.get(CONF_PRIORITIZE_UNDELIVERED, DEFAULT_PRIORITIZE_UNDELIVERED)),
            max_shipments=int(data.get(CONF_MAX_SHIPMENTS, DEFAULT_MAX_SHIPMENTS)),
            max_outgoing_shipments=int(data.get(CONF_MAX_OUTGOING_SHIPMENTS, DEFAULT_MAX_OUTGOING_SHIPMENTS)),
            stale_shipment_day_limit=int(data.get(CONF_STALE_SHIPMENT_DAY_LIMIT, DEFAULT_STALE_SHIPMENT_DAY_LIMIT)),
            completed_shipment_days_shown=int(data.get(CONF_COMPLETED_SHIPMENT_DAYS_SHOWN, DEFAULT_COMPLETED_SHIPMENT_DAYS_SHOWN)),
            pickup_code=str(data.get(CONF_PICKUP_CODE, DEFAULT_PICKUP_CODE)),
        )


@dataclass(frozen=True)
class Packages:
    # When a shipment of the account last changed, hidden ones included. None when there are none.
    latest_change: datetime | None
    # The packages to list, newest first and at most the maximum of each direction.
    packages: list[dict[str, Any]]
    # Every package within the age limits, however many: the counts.
    current: list[dict[str, Any]]
    # Every package of the account by its number: what happens to them, also outside the list.
    every: dict[str, dict[str, Any]]


def map_status(raw_status: Any) -> int:
    return STATUS_MAP.get(str(raw_status or "").upper(), STATUS_UNKNOWN)


def map_direction(raw_direction: Any) -> str | None:
    return DIRECTION_MAP.get(str(raw_direction or "").upper())


def limit_of(item: Mapping[str, Any], settings: PackageSettings) -> int:
    """The most packages of the item's direction listed. One whose direction isn't known goes with the incoming ones."""
    return settings.max_outgoing_shipments if item.get("direction") == DIRECTION_OUTGOING else settings.max_shipments


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

    newest: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for shipment in shipments:
        changed = status_change_time(shipment)
        if changed is None:
            continue
        item = package(shipment, changed, settings)
        # A direction whose maximum is 0 is left out altogether: not listed, counted, reported in events or in the time
        # of the latest change.
        if limit_of(item, settings) == 0:
            continue
        if latest_change is None or changed > latest_change:
            latest_change = changed

        keep_newest(newest, changed, item)

    every = {number: item for number, (_, item) in newest.items()}
    for changed, item in newest.values():
        status = item["status"]
        # The limits are whole days of age, so a package two days and an hour old is past a limit of two.
        age = now - changed
        if status not in COMPLETED_STATUSES and age <= timedelta(days=settings.stale_shipment_day_limit):
            undelivered.append((changed, item))
        elif status in COMPLETED_STATUSES and age <= timedelta(days=settings.completed_shipment_days_shown):
            completed.append((changed, item))

    undelivered.sort(key=change_time, reverse=True)
    completed.sort(key=change_time, reverse=True)
    ordered = undelivered + completed
    if not settings.prioritize_undelivered:
        ordered.sort(key=change_time, reverse=True)
    current = [item for _, item in ordered]
    # Each direction up to its own maximum, so many sent packages don't push the incoming ones off the list.
    listed: list[dict[str, Any]] = []
    taken = {False: 0, True: 0}
    for item in current:
        sent = item.get("direction") == DIRECTION_OUTGOING
        if taken[sent] < limit_of(item, settings):
            taken[sent] += 1
            listed.append(item)
    return Packages(latest_change, listed, current, every)


def keep_newest(newest: dict[str, tuple[datetime, dict[str, Any]]], changed: datetime, item: dict[str, Any]) -> None:
    """Keeps a package by its number, the newest copy when the account lists one twice. One without a number is left out,
    since nothing would tell its updates apart from another's."""
    number = item.get("shipment_number")
    if not number:
        return
    if number not in newest or changed > newest[number][0]:
        newest[number] = (changed, item)


def change_time(item: tuple[datetime, dict[str, Any]]) -> datetime:
    return item[0]


def items_of(shipment: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The items of a shipment, leaving out anything in the list that isn't one."""
    items = shipment.get("items")
    return [item for item in items if isinstance(item, Mapping)] if isinstance(items, list) else []


def first_item(shipment: Mapping[str, Any]) -> Mapping[str, Any]:
    items = items_of(shipment)
    return items[0] if items else {}


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
        "direction": map_direction(user_data.get("direction")),
        "raw_status": raw_status,
        "latest_event": event.get("eventDescription") or text_of(item.get("statusText")),
        "latest_event_city": location.get("city") or location.get("locationName"),
        # Where the event happened, and the receiver's country when PostNord doesn't say.
        "latest_event_country": location.get("countryCode") or consignee.get("countryCode"),
        "latest_event_date": changed.isoformat(),
        # Only on active parcels; absent (None) on delivered ones. Field names are tentative
        # until an active parcel is captured.
        "estimated_delivery": iso(parse_time(shipment.get("estimatedTimeOfArrival") or shipment.get("publicTimeOfArrival"))),
        "pickup_deadline": None,
        "weight": number(measure(item.get("weight"))),
        "package_count": item_count(shipment),
        "pickup_point": pickup_point(point, consignee),
        # Only a setting that asks for the code shows it: an unknown value keeps it out, as the code is a secret.
        "pickup_code": pickup_code(shipment) if settings.pickup_code == PICKUP_CODE_CODE else None,
        "pickup_qr": None,
        "source": "PostNord",
        "tracking_url": tracking_url(shipment_number),
    }


def item_count(shipment: Mapping[str, Any]) -> int | None:
    return len(items_of(shipment)) or None


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
    the field names are tentative until one is captured, so read defensively."""
    address = point.get("address") if isinstance(point.get("address"), Mapping) else point
    # The card shows opening hours as a line of text. Their shape hasn't been seen yet, so anything else is left out.
    hours = point.get("openingHours")
    found = {
        "name": point.get("name"),
        "street": address.get("street") or address.get("streetName"),
        "postal_code": address.get("postCode") or address.get("postalCode"),
        "city": address.get("city") or consignee.get("city"),
        "type": point.get("type"),
        "available": hours if isinstance(hours, str) and hours else None,
    }
    # Without a name it is no pickup point, only the receiver's city: a home delivery has nothing else.
    return found if found["name"] else None


def pickup_code(shipment: Mapping[str, Any]) -> str | None:
    """The code that collects the package, which the integration can't get yet.

    PostNord serves it behind a strong-auth (levelled-up) token, from collectcode/{collectCode}. So a collectCode on the
    parcel would be the key of that lookup, not the code, and must not be shown as one. Left for a later version."""
    return None


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
