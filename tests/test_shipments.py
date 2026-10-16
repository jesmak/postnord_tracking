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
    pickup_code="none",
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
        "origin": "Example Shop",
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
        "pickup_qr": None,
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
            archived=[shipment("PN0200", "DELIVERED", event="Lähetys on toimitettu", delivery_date="2026-09-16T05:00:00Z")],
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
    """A parcel with the extra fields active parcels carry (tentative shape)."""
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


def test_the_pickup_point_is_always_there_but_the_code_only_when_asked_for() -> None:
    [package] = build_packages(tracking(active=[with_details()], archived=[]), SETTINGS, NOW).packages
    assert package["pickup_point"]["name"] == "PostNord Service Point"
    assert package["pickup_code"] is None
    assert package["pickup_qr"] is None


def test_the_pickup_point_and_no_code_even_when_asked_for() -> None:
    """A collectCode on the parcel is the key of the code's lookup, not the code, so it is never shown as one."""
    settings = replace(SETTINGS, pickup_code="code")
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
    assert package["pickup_code"] is None


def test_the_counts_and_events_see_every_package_not_only_the_listed_ones() -> None:
    moving = [shipment(f"PN03{n}", "EN_ROUTE", f"2026-09-16T0{n}:00:00Z") for n in range(1, 4)]
    stale = shipment("PN0399", "EN_ROUTE", "2026-08-01T05:00:00Z")
    packages = build_packages(tracking(active=[*moving, stale], archived=[]), replace(SETTINGS, max_shipments=2), NOW)
    assert len(packages.packages) == 2
    assert len(packages.current) == 3, "a count covers all of them, but not one gone stale"
    assert len(packages.every) == 4, "events follow every package, stale ones too"


def test_a_parcel_both_active_and_archived_is_kept_once_as_its_newest_copy() -> None:
    newer = shipment("PN0600", "DELIVERED", "2026-09-16T08:30:00Z")
    older = shipment("PN0600", "EN_ROUTE", "2026-09-16T05:30:00Z")
    for active, archived in (([newer], [older]), ([older], [newer])):
        packages = build_packages(tracking(active=active, archived=archived), SETTINGS, NOW)
        assert {number: package["status"] for number, package in packages.every.items()} == {"PN0600": 0}


def test_the_event_country_is_where_it_happened() -> None:
    moved = shipment("PN0700", "EN_ROUTE", "2026-09-16T08:30:00Z")
    moved["items"][0]["events"][-1]["location"] = {"name": "Malmö", "countryCode": "SE"}
    [package] = build_packages(tracking(active=[moved], archived=[]), SETTINGS, NOW).packages
    assert package["latest_event_country"] == "SE"


@pytest.mark.parametrize(("delivered", "shown"), [("2026-09-13T10:00:00Z", True), ("2026-09-13T08:00:00Z", False)])
def test_the_days_shown_are_counted_from_the_exact_time(delivered: str, shown: bool) -> None:
    # Three days before NOW is 2026-09-13 09:00, so an hour more is past the limit of three.
    parcel = shipment("PN0800", "DELIVERED", delivered)
    packages = build_packages(tracking(active=[], archived=[parcel]), SETTINGS, NOW)
    assert numbers(packages) == (["PN0800"] if shown else [])


@pytest.mark.parametrize(("changed", "shown"), [("2026-09-01T10:00:00Z", True), ("2026-09-01T08:00:00Z", False)])
def test_the_stale_limit_is_counted_from_the_exact_time(changed: str, shown: bool) -> None:
    parcel = shipment("PN0810", "EN_ROUTE", changed)
    packages = build_packages(tracking(active=[parcel], archived=[]), SETTINGS, NOW)
    assert numbers(packages) == (["PN0810"] if shown else [])


def test_a_null_among_the_items_is_left_out() -> None:
    parcel = shipment("PN0900", "EN_ROUTE", "2026-09-16T08:30:00Z", event="Lähetys on kuljetuksessa")
    parcel["items"] = [None, *parcel["items"]]
    [package] = build_packages(tracking(active=[parcel], archived=[]), SETTINGS, NOW).packages
    assert package["latest_event"] == "Lähetys on kuljetuksessa"
    assert package["latest_event_date"] == "2026-09-16T08:30:00+00:00"
    assert package["package_count"] == 1


@pytest.mark.parametrize(
    ("hours", "available"), [("Mon-Fri 8-20", "Mon-Fri 8-20"), ([{"day": "MONDAY", "open": "08:00"}], None), ("", None)]
)
def test_opening_hours_are_passed_on_only_as_text(hours: Any, available: str | None) -> None:
    parcel = with_details()
    parcel["destinationDeliveryPoint"]["openingHours"] = hours
    [package] = build_packages(tracking(active=[parcel], archived=[]), SETTINGS, NOW).packages
    assert package["pickup_point"]["available"] == available
