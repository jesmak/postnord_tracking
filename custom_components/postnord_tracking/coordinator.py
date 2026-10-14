"""Fetching the parcels of an account every 10 minutes."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import PostNordAuthError, PostNordClient, PostNordError
from .const import CONF_ACCESS_TOKEN, CONF_LANGUAGE, CONF_REFRESH_TOKEN, CONF_USERNAME, DOMAIN, UPDATE_INTERVAL
from .shipments import Packages, PackageSettings, build_packages

_LOGGER = logging.getLogger(__name__)

type PostNordConfigEntry = ConfigEntry[PostNordCoordinator]


class PostNordCoordinator(DataUpdateCoordinator[Packages]):
    config_entry: PostNordConfigEntry

    def __init__(self, hass: HomeAssistant, entry: PostNordConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            # Not the title, which is the account's email, so the integration's own update errors don't name the account
            # in logs that end up in bug reports. Home Assistant still logs the title itself when setting up.
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.settings = PackageSettings.from_data(entry.data)
        self.client = PostNordClient(
            async_get_clientsession(hass),
            entry.data.get(CONF_ACCESS_TOKEN, ""),
            entry.data[CONF_REFRESH_TOKEN],
            entry.data[CONF_LANGUAGE],
            self._save_access_token,
        )

    @callback
    def _save_access_token(self, access_token: str) -> None:
        """Keeps the refreshed tokens, so the next start doesn't begin with an expired one.

        PostNord may rotate the refresh token, so that is saved too; otherwise the next refresh
        would use a spent token and fail.
        """
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={
                **self.config_entry.data,
                CONF_ACCESS_TOKEN: access_token,
                CONF_REFRESH_TOKEN: self.client.refresh_token,
            },
        )

    @property
    def device_info(self) -> DeviceInfo:
        """The account as a device, which all of its entities belong to."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.entry_id)},
            translation_key="account",
            translation_placeholders={"username": self.config_entry.data[CONF_USERNAME]},
            manufacturer="PostNord",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def _async_update_data(self) -> Packages:
        try:
            tracking = await self.client.tracking()
        except PostNordAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PostNordError as err:
            raise UpdateFailed(str(err)) from err
        return build_packages(tracking, self.settings, dt_util.now())
