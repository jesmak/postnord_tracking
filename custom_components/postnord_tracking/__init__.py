"""PostNord package tracking: the coming and recently delivered parcels of a PostNord account.

Each config entry is one account, with a sensor that lists its packages in the format
package-tracker-card shows, alongside Posti and Matkahuolto.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
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
