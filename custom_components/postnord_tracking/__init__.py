"""PostNord package tracking: the coming and recently delivered parcels of a PostNord account.

Each config entry is one account, with a sensor that lists its packages in the format
package-tracker-card shows, alongside Posti and Matkahuolto.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import CONF_INCLUDE_PICKUP_DETAILS, CONF_PICKUP_CODE, DOMAIN, PICKUP_CODE_CODE, PICKUP_CODE_NONE
from .coordinator import PostNordConfigEntry, PostNordCoordinator

PLATFORMS = [Platform.EVENT, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: PostNordConfigEntry) -> bool:
    coordinator = PostNordCoordinator(hass, entry)
    # A refresh token that no longer works starts reauthentication; PostNord being down retries later.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PostNordConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: PostNordConfigEntry) -> bool:
    """Turns the pickup switch of 1.1 entries into a choice: the pickup point is now always included."""
    if entry.version != 1:
        return False
    if entry.minor_version < 2:
        data = {key: value for key, value in entry.data.items() if key != CONF_INCLUDE_PICKUP_DETAILS}
        data[CONF_PICKUP_CODE] = PICKUP_CODE_CODE if entry.data.get(CONF_INCLUDE_PICKUP_DETAILS) else PICKUP_CODE_NONE
        hass.config_entries.async_update_entry(entry, data=data, minor_version=2)
    return True
