"""Config flow: an account is added by logging in to PostNord in a browser, then choosing settings.

PostNord's OAuth client only accepts the app's own redirect, which a browser can't open. So the login
step shows the login link, the user copies the redirect URL the login ends with from the browser's
developer tools, and pastes it; the flow exchanges its code for the tokens and asks PostNord for the
account's email address, which names the account. The settings come in a step of their own.

The coordinator saves refreshed tokens; when the refresh token stops working, reauthentication logs
in again. Reconfiguring offers a choice: change the settings, or log in again.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .api import PostNordAuthError, PostNordClient, PostNordError, PostNordLogin, PostNordRedirectError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_COMPLETED_SHIPMENT_DAYS_SHOWN,
    CONF_INCLUDE_PICKUP_DETAILS,
    CONF_LANGUAGE,
    CONF_MAX_SHIPMENTS,
    CONF_PRIORITIZE_UNDELIVERED,
    CONF_REDIRECT_URL,
    CONF_REFRESH_TOKEN,
    CONF_STALE_SHIPMENT_DAY_LIMIT,
    CONF_USERNAME,
    DEFAULT_COMPLETED_SHIPMENT_DAYS_SHOWN,
    DEFAULT_INCLUDE_PICKUP_DETAILS,
    DEFAULT_MAX_SHIPMENTS,
    DEFAULT_PRIORITIZE_UNDELIVERED,
    DEFAULT_STALE_SHIPMENT_DAY_LIMIT,
    DOMAIN,
    LANGUAGES,
)

DAYS_SELECTOR = NumberSelector(NumberSelectorConfig(min=0, max=365, step=1, mode=NumberSelectorMode.BOX))

LOGIN_SCHEMA = vol.Schema({vol.Required(CONF_REDIRECT_URL): TextSelector()})
SETTINGS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LANGUAGE): SelectSelector(
            SelectSelectorConfig(options=LANGUAGES, translation_key=CONF_LANGUAGE, mode=SelectSelectorMode.DROPDOWN)
        ),
        vol.Required(CONF_PRIORITIZE_UNDELIVERED): BooleanSelector(),
        vol.Required(CONF_MAX_SHIPMENTS): NumberSelector(
            NumberSelectorConfig(min=1, max=50, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_STALE_SHIPMENT_DAY_LIMIT): DAYS_SELECTOR,
        vol.Required(CONF_COMPLETED_SHIPMENT_DAYS_SHOWN): DAYS_SELECTOR,
        vol.Required(CONF_INCLUDE_PICKUP_DETAILS): BooleanSelector(),
    }
)


def clean_settings(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Submitted settings, normalised for storing."""
    data = dict(user_input)
    for key in (CONF_MAX_SHIPMENTS, CONF_STALE_SHIPMENT_DAY_LIMIT, CONF_COMPLETED_SHIPMENT_DAYS_SHOWN):
        if key in data:
            data[key] = int(data[key])
    return data


class PostNordConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        # One login per flow: the link on the form stays the same when the form is shown again,
        # so logging in again with it after an error works.
        self._login = PostNordLogin()
        # The logged-in account (email and tokens), between the login and settings steps.
        self._account: dict[str, str] = {}

    async def _log_in(self, pasted: str, language: str) -> dict[str, str]:
        """Exchanges the pasted redirect for tokens, and checks them by reading the parcels.

        Returns the errors; on success, the account's email and tokens are in self._account.
        """
        session = async_get_clientsession(self.hass)
        try:
            access_token, refresh_token = await self._login.exchange(session, pasted)
            client = PostNordClient(session, access_token, refresh_token, language)
            email = await client.email()
            await client.tracking()
        except PostNordRedirectError as err:
            return {CONF_REDIRECT_URL: err.reason}
        except PostNordAuthError:
            return {"base": "invalid_auth"}
        except PostNordError:
            return {"base": "cannot_connect"}
        self._account = {
            CONF_USERNAME: email,
            CONF_ACCESS_TOKEN: client.access_token,
            CONF_REFRESH_TOKEN: client.refresh_token,
        }
        return {}

    def _tokens(self) -> dict[str, str]:
        """The new tokens alone: an entry keeps its username, which its entities' ids are built from."""
        return {key: self._account[key] for key in (CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN)}

    def _show_login(self, step_id: str, errors: dict[str, str], **placeholders: str) -> ConfigFlowResult:
        return self.async_show_form(
            step_id=step_id,
            data_schema=LOGIN_SCHEMA,
            errors=errors,
            description_placeholders={"login_url": self._login.url, **placeholders},
        )

    def _language(self) -> str:
        language = self.hass.config.language[:2]
        return language if language in LANGUAGES else "en"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Logging in."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._log_in(user_input[CONF_REDIRECT_URL], self._language())
            if not errors:
                await self.async_set_unique_id(self._account[CONF_USERNAME].lower())
                self._abort_if_unique_id_configured()
                return await self.async_step_settings()
        return self._show_login("user", errors)

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The settings of a newly logged-in account."""
        email = self._account[CONF_USERNAME]
        if user_input is not None:
            return self.async_create_entry(title=email, data={**self._account, **clean_settings(user_input)})

        defaults = {
            CONF_LANGUAGE: self._language(),
            CONF_PRIORITIZE_UNDELIVERED: DEFAULT_PRIORITIZE_UNDELIVERED,
            CONF_MAX_SHIPMENTS: DEFAULT_MAX_SHIPMENTS,
            CONF_STALE_SHIPMENT_DAY_LIMIT: DEFAULT_STALE_SHIPMENT_DAY_LIMIT,
            CONF_COMPLETED_SHIPMENT_DAYS_SHOWN: DEFAULT_COMPLETED_SHIPMENT_DAYS_SHOWN,
            CONF_INCLUDE_PICKUP_DETAILS: DEFAULT_INCLUDE_PICKUP_DETAILS,
        }
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(SETTINGS_SCHEMA, defaults),
            description_placeholders={"username": email},
        )

    async def _log_in_again(self, entry: ConfigEntry, user_input: dict[str, Any]) -> dict[str, str]:
        """Logging in again to the account of an entry. Returns the errors."""
        errors = await self._log_in(user_input[CONF_REDIRECT_URL], entry.data[CONF_LANGUAGE])
        if not errors and self._account[CONF_USERNAME].lower() != entry.unique_id:
            errors = {"base": "wrong_account"}
        return errors

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """A new login, when PostNord no longer accepts the saved one."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._log_in_again(entry, user_input)
            if not errors:
                return self.async_update_reload_and_abort(entry, data={**entry.data, **self._tokens()})
        return self._show_login("reauth_confirm", errors, username=entry.data[CONF_USERNAME])

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Changing the settings, or logging in again."""
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["reconfigure_settings", "reconfigure_login"],
            description_placeholders={"username": self._get_reconfigure_entry().data[CONF_USERNAME]},
        )

    async def async_step_reconfigure_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_reload_and_abort(entry, data={**entry.data, **clean_settings(user_input)})
        return self.async_show_form(
            step_id="reconfigure_settings",
            data_schema=self.add_suggested_values_to_schema(SETTINGS_SCHEMA, dict(entry.data)),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
        )

    async def async_step_reconfigure_login(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._log_in_again(entry, user_input)
            if not errors:
                return self.async_update_reload_and_abort(entry, data={**entry.data, **self._tokens()})
        return self._show_login("reconfigure_login", errors, username=entry.data[CONF_USERNAME])
