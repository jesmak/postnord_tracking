"""Constants for the PostNord package tracking integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "postnord_tracking"

ATTRIBUTION: Final = "Data provided by PostNord Group AB"

# The carrier's own page for a package, given with each package so that package-tracker-card can open it.
TRACKING_URL: Final = "https://tracking.postnord.com/?id={number}"

# The app's own gateway. The subscription key rides in the query string (?apikey=), the OAuth
# token in Authorization, and every call carries the context header. See NOTES.md in the repo root.
API_BASE_URL: Final = "https://api2.postnord.com/rest"
PATH_TRACKING: Final = "/customer/v2/receiverapp/tracking"
API_KEY: Final = "1ecf161be47543b19fce03f953a6e8d2"
CONTEXT: Final = "mobileapp"
USER_AGENT: Final = "okhttp/4.12.0"

# OAuth. The app is a public client (no secret) with PKCE; the refresh token renews the access token.
# Only the app's own redirect is registered, so the browser can't return to Home Assistant: the user
# copies the redirect URL from the browser's developer tools and pastes it into the config flow.
AUTHORIZE_URL: Final = "https://account.postnord.com/auth"
TOKEN_URL: Final = "https://account.postnord.com/oauth2/token"
# OpenID userinfo: the account's email address, which names the account in Home Assistant.
USERINFO_URL: Final = "https://account.postnord.com/userinfo"
CLIENT_ID: Final = "receiverappprod3gvTgY5ATtYWZZy"
REDIRECT_URI: Final = "com.postnord.app://redirect"
SCOPES: Final = [
    "openid",
    "offline_access",
    "https://api.postnord.com/scopes/shipment/eventsorterservice/recipient",
    "https://api.postnord.com/scopes/receiverapp-bff/track",
    "https://api.postnord.com/scopes/trackedshipments/track",
    "https://api.postnord.com/scopes/recipientinstructions/read",
    "https://api.postnord.com/scopes/eta/livetracking",
    "https://api.postnord.com/scopes/preferences/recipient",
]

# Languages of the package event descriptions (PostNord localises statusText by Accept-Language).
LANGUAGES: Final = ["fi", "sv", "nb", "da", "en"]

# Config entry data.
CONF_USERNAME: Final = "username"
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_REFRESH_TOKEN: Final = "refresh_token"
# Only in the forms: the pasted redirect URL, exchanged for the tokens above.
CONF_REDIRECT_URL: Final = "redirect_url"
CONF_LANGUAGE: Final = "language"
CONF_PRIORITIZE_UNDELIVERED: Final = "prioritize_undelivered"
CONF_MAX_SHIPMENTS: Final = "max_shipments"
CONF_STALE_SHIPMENT_DAY_LIMIT: Final = "stale_shipment_day_limit"
CONF_COMPLETED_SHIPMENT_DAYS_SHOWN: Final = "completed_shipment_day_shown"
CONF_INCLUDE_PICKUP_DETAILS: Final = "include_pickup_details"

DEFAULT_PRIORITIZE_UNDELIVERED: Final = True
# The pickup point and its code are left out unless asked for: the code collects the package.
DEFAULT_INCLUDE_PICKUP_DETAILS: Final = False
DEFAULT_MAX_SHIPMENTS: Final = 5
DEFAULT_STALE_SHIPMENT_DAY_LIMIT: Final = 15
DEFAULT_COMPLETED_SHIPMENT_DAYS_SHOWN: Final = 3

UPDATE_INTERVAL: Final = timedelta(minutes=10)
