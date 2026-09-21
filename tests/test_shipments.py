"""Turning PostNord's tracking response into the sensor's packages."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from custom_components.postnord_tracking.shipments import Packages, PackageSettings, build_packages, map_status

from .conftest import NOW, shipment, tracking

SETTINGS = PackageSettings(
    prioritize_undelivered=True,
    max_shipments=5,
    stale_shipment_day_limit=15,
    completed_shipment_days_shown=3,
    include_pickup_details=False,
)


def numbers(packages: Packages) -> list[str]:
    return [package["shipment_number"] for package in packages.packages]


@pytest.mark.parametrize(
    ("raw_status", "status"),
    [
        ("CREATED", 1),
        ("INFORMED", 1),
        ("EN_ROUTE", 3),
        ("DELAYED", 3),
        ("AVAILABLE_FOR_DELIVERY", 5),
        ("DELIVERED", 0),
        ("RETURNED", 6),
        ("DELIVERY_REFUSED", 6),
        ("DELIVERY_IMPOSSIBLE", 7),
        ("OTHER", 7),
        ("SOMETHING_NEW", 7),
        (None, 7),
    ],
)
def test_postnord_statuses(raw_status: Any, status: int) -> None:
    assert map_status(raw_status) == status


def test_undelivered_packages_come_first_and_old_ones_are_hidden() -> None:
    packages = build_packages(tracking(), SETTINGS, NOW)
    assert numbers(packages) == ["PN0002", "PN0001", "PN0006", "PN0003"]
    assert packages.latest_change.isoformat() == "2026-09-16T08:30:00+00:00"


def test_newest_first_when_undelivered_packages_are_not_prioritised() -> None:
    settings = replace(SETTINGS, prioritize_undelivered=False, max_shipments=3)
    assert numbers(build_packages(tracking(), settings, NOW)) == ["PN0002", "PN0006", "PN0001"]


def test_active_and_archived_parcels_are_both_listed() -> None:
    # PN0002 is active (in transport), PN0003 archived (delivered): both come through.
    numbers_shown = numbers(build_packages(tracking(), SETTINGS, NOW))
    assert "PN0002" in numbers_shown
    assert "PN0003" in numbers_shown


def test_package_attributes() -> None:
    _, ready, _delivered_no_events, _ = build_packages(tracking(), SETTINGS, NOW).packages
    assert ready == {
        "origin": "Verkkokauppa.com",
        "origin_city": "Stockholm",
        "destination": None,
        "destination_city": "Tampere",
        "shipment_number": "PN0001",
        "shipment_date": "2026-09-14T06:00:00+00:00",
        "status": 5,
        "raw_status": "AVAILABLE_FOR_DELIVERY",
        "latest_event": "Lähetys on noudettavissa",
        "latest_event_city": "Tampere",
        "latest_event_country": "FI",
        "latest_event_date": "2026-09-15T10:00:00+00:00",
        "estimated_delivery": None,
        "pickup_deadline": None,
        "weight": None,
        "package_count": 1,
        "pickup_point": None,
        "pickup_code": None,
        "source": "PostNord",
        "tracking_url": "https://tracking.postnord.com/?id=PN0001",
    }


def test_the_newest_event_is_the_latest_one() -> None:
    parcel = shipment("PN0100", "EN_ROUTE")
    parcel["items"][0]["events"] = [
        {"eventDescription": "Older", "eventTime": "2026-09-16T06:00:00Z", "location": {"city": "Malmö"}},
        {"eventDescription": "Newest", "eventTime": "2026-09-16T08:00:00Z", "location": {"city": "Tampere"}},
    ]
    [package] = build_packages(tracking(active=[parcel], archived=[]), SETTINGS, NOW).packages
    assert package["latest_event"] == "Newest"
    assert package["latest_event_date"] == "2026-09-16T08:00:00+00:00"


def test_a_parcel_delivered_from_its_delivery_date_without_events() -> None:
    # With no events, the delivery date is the change time and the status line stands in as the event.
    [delivered] = build_packages(
        tracking(
            active=[],
            archived=[
                shipment("PN0200", "DELIVERED", event="Lähetys on toimitettu", delivery_date="2026-09-16T05:00:00Z")
            ],
        ),
        SETTINGS,
        NOW,
    ).packages
    assert delivered["status"] == 0
    assert delivered["latest_event"] == "Lähetys on toimitettu"
    assert delivered["latest_event_date"] == "2026-09-16T05:00:00+00:00"


def test_an_account_without_parcels() -> None:
    packages = build_packages(tracking(active=[], archived=[]), SETTINGS, NOW)
    assert (packages.latest_change, packages.packages) == (None, [])


def with_details(**changes: Any) -> dict[str, Any]:
    """A parcel with the extra fields active parcels carry (tentative shape, see NOTES.md)."""
    data = shipment("PN0020", "AVAILABLE_FOR_DELIVERY", "2026-09-16T08:00:00Z")
    data["estimatedTimeOfArrival"] = "2026-09-17T07:00:00Z"
    data["destinationDeliveryPoint"] = {
        "name": "PostNord Service Point",
        "type": "SERVICE_POINT",
        "address": {"street": "Storgatan 1", "postCode": "11122", "city": "Tampere"},
    }
    data["collectCode"] = "12345678"
    data["items"][0]["weight"] = {"unit": "kg", "value": "2.4"}
    data["items"].append({"itemId": "PN0020-2", "status": "AVAILABLE_FOR_DELIVERY"})
    data.update(changes)
    return data


def test_a_package_carries_what_postnord_knows_of_it() -> None:
    [package] = build_packages(tracking(active=[with_details()], archived=[]), SETTINGS, NOW).packages
    assert package["estimated_delivery"] == "2026-09-17T07:00:00+00:00"
    assert package["weight"] == 2.4
    assert package["package_count"] == 2


def test_the_pickup_point_and_its_code_are_left_out_unless_asked_for() -> None:
    [package] = build_packages(tracking(active=[with_details()], archived=[]), SETTINGS, NOW).packages
    assert package["pickup_point"] is None
    assert package["pickup_code"] is None


def test_the_pickup_point_and_its_code_when_asked_for() -> None:
    settings = replace(SETTINGS, include_pickup_details=True)
    [package] = build_packages(tracking(active=[with_details()], archived=[]), settings, NOW).packages
    assert package["pickup_point"] == {
        "name": "PostNord Service Point",
        "street": "Storgatan 1",
        "postal_code": "11122",
        "city": "Tampere",
        "type": "SERVICE_POINT",
        "available": None,
    }
    assert package["destination"] == "PostNord Service Point"
    assert package["pickup_code"] == "12345678"
