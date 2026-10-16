"""Constants for the PostNord package tracking integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "postnord_tracking"

ATTRIBUTION: Final = "Data provided by PostNord Group AB"

# The carrier's own page for a package, given with each package so that package-tracker-card can open it.
TRACKING_URL: Final = "https://tracking.postnord.com/?id={number}"

# The app's own gateway. The subscription key rides in the query string (?apikey=), the OAuth
# token in Authorization, and every call carries the context header.
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
# OpenID userinfo: the account's email address, which names the account in Home Assistant, and its subject.
USERINFO_URL: Final = "https://account.postnord.com/userinfo"
# Revoking the refresh token when the entry is removed, so a copy of it left in backups can no longer log in.
REVOKE_URL: Final = "https://account.postnord.com/oauth2/revoke"
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
# The account's OpenID subject, which stays the same when its email changes. Saved by every login since 1.2.0.
CONF_SUBJECT: Final = "subject"
# Only in the forms: the pasted redirect URL, exchanged for the tokens above.
CONF_REDIRECT_URL: Final = "redirect_url"
CONF_LANGUAGE: Final = "language"
CONF_PRIORITIZE_UNDELIVERED: Final = "prioritize_undelivered"
# The most incoming packages listed, and the most sent ones. 0 leaves that direction out altogether.
CONF_MAX_SHIPMENTS: Final = "max_shipments"
CONF_MAX_OUTGOING_SHIPMENTS: Final = "max_outgoing_shipments"
CONF_STALE_SHIPMENT_DAY_LIMIT: Final = "stale_shipment_day_limit"
CONF_COMPLETED_SHIPMENT_DAYS_SHOWN: Final = "completed_shipment_day_shown"
# Whether packages carry their pickup code. Before config entry version 1.2 (release 1.1.0) this was
# include_pickup_details, a switch that also held back the pickup point.
CONF_PICKUP_CODE: Final = "pickup_code"
CONF_INCLUDE_PICKUP_DETAILS: Final = "include_pickup_details"

DEFAULT_PRIORITIZE_UNDELIVERED: Final = True
PICKUP_CODE_NONE: Final = "none"
PICKUP_CODE_CODE: Final = "code"
PICKUP_CODE_OPTIONS: Final = [PICKUP_CODE_NONE, PICKUP_CODE_CODE]
# The code is left out unless asked for, since it collects the package.
DEFAULT_PICKUP_CODE: Final = PICKUP_CODE_NONE
DEFAULT_MAX_SHIPMENTS: Final = 5
DEFAULT_MAX_OUTGOING_SHIPMENTS: Final = 5
DEFAULT_STALE_SHIPMENT_DAY_LIMIT: Final = 15
DEFAULT_COMPLETED_SHIPMENT_DAYS_SHOWN: Final = 3

UPDATE_INTERVAL: Final = timedelta(minutes=10)
