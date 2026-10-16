"""The sensor of an account: when its packages last changed, with the packages in its attributes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, CONF_USERNAME
from .coordinator import PostNordConfigEntry, PostNordCoordinator
from .shipments import COMPLETED_STATUSES, DIRECTION_OUTGOING, STATUS_READY_FOR_PICKUP

ATTR_PACKAGES = "packages"


# The coordinator fetches for every entity at once, so the entities themselves update nothing.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PostNordConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            PostNordSensor(coordinator),
            # The account's own packages, and those it has sent. A package whose direction isn't known is taken as its own.
            PostNordCountSensor(coordinator, "on_the_way", lambda package: not sent(package) and on_the_way(package)),
            PostNordCountSensor(coordinator, "ready_for_pickup", lambda package: not sent(package) and ready(package)),
            PostNordCountSensor(coordinator, "outgoing_on_the_way", lambda package: sent(package) and on_the_way(package)),
            PostNordCountSensor(coordinator, "outgoing_ready_for_pickup", lambda package: sent(package) and ready(package)),
        ]
    )


def sent(package: Mapping[str, Any]) -> bool:
    return package.get("direction") == DIRECTION_OUTGOING


def on_the_way(package: Mapping[str, Any]) -> bool:
    return package.get("status") not in COMPLETED_STATUSES


def ready(package: Mapping[str, Any]) -> bool:
    return package.get("status") == STATUS_READY_FOR_PICKUP


class PostNordSensor(CoordinatorEntity[PostNordCoordinator], SensorEntity):
    """The time a package of the account last changed, such as when it arrived or was delivered."""

    # The packages change with every event and would fill the database; the state is history enough.
    _unrecorded_attributes = frozenset({ATTR_PACKAGES})
    _attr_attribution = ATTRIBUTION
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_has_entity_name = True
    _attr_name = None
    # Names nothing, as the sensor is the device itself, but gives it its icon in icons.json.
    _attr_translation_key = "packages"

    def __init__(self, coordinator: PostNordCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        username = entry.data[CONF_USERNAME]
        self._attr_unique_id = f"postnord_{username}"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.latest_change if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_PACKAGES: self.coordinator.data.packages if self.coordinator.data else []}


class PostNordCountSensor(CoordinatorEntity[PostNordCoordinator], SensorEntity):
    """How many of the account's packages, or of those it has sent, are on their way or waiting to be picked up."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PostNordCoordinator, key: str, counts: Callable[[Mapping[str, Any]], bool]) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        username = entry.data[CONF_USERNAME]
        self._counts = counts
        self._attr_translation_key = key
        self._attr_unique_id = f"postnord_{username}_{key}"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        if data is None:
            return None
        # All of them, not only those the list has room for.
        return sum(1 for package in data.current if self._counts(package))
