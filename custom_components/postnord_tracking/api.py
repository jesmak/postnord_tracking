"""PostNord's app API: the account's parcels, active and archived.

Requests carry the OAuth access token of a PostNord login. When it has expired, the refresh
token gets a new one. When that fails too, the account has to be logged in again (`PostNordLogin`,
driven by the config flow). The gateway's subscription key rides in the query string, and every
call sends the app's context header.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, unquote, urlencode

import aiohttp

from .const import (
    API_BASE_URL,
    API_KEY,
    AUTHORIZE_URL,
    CLIENT_ID,
    CONTEXT,
    PATH_TRACKING,
    REDIRECT_URI,
    REVOKE_URL,
    SCOPES,
    TOKEN_URL,
    USER_AGENT,
    USERINFO_URL,
)

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=20)


# The OAuth errors that mean the login itself is gone, and only a new one helps.
REFUSED_GRANTS = ("invalid_grant", "invalid_client", "unauthorized_client")

# The parcel lists of a tracking answer. An answer without them is no account with no parcels.
SHIPMENT_LISTS = ("activeShipments", "archivedShipments")

# Where an answer that isn't what was asked for may say why.
ERROR_FIELDS = ("error", "error_description", "message", "fault")


class PostNordError(Exception):
    """PostNord couldn't be reached, or it answered with an error."""


class PostNordAuthError(PostNordError):
    """The login doesn't work, or no longer works, and the account has to log in again."""


class PostNordRedirectError(PostNordError):
    """The pasted text isn't the redirect of this login."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        # "no_code": no authorization code in it; "wrong_state": the redirect of another login.
        self.reason = reason


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _query_value(text: str, name: str) -> str | None:
    match = re.search(rf"[?&]{name}=([^&#\s\"']+)", text)
    return unquote(match.group(1)) if match else None


def _why(body: Any) -> str:
    """What an unexpected answer says about itself, for the error message."""
    if not isinstance(body, dict):
        return ""
    said = [f"{key} {str(body[key])[:200]!r}" for key in ERROR_FIELDS if body.get(key)]
    return f": {', '.join(said)}" if said else ""


async def _token_post(session: aiohttp.ClientSession, url: str, data: dict[str, str], purpose: str) -> tuple[int, dict[str, Any] | None]:
    """A form POST to PostNord's OAuth server. The body is None when it isn't a JSON object, such as an empty 401 or a
    firewall's HTML page."""
    try:
        async with session.post(
            url,
            data=data,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=TIMEOUT,
        ) as response:
            status = response.status
            text = await response.text()
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise PostNordError(f"PostNord couldn't be reached {purpose}: {err}") from err
    try:
        body = json.loads(text)
    except ValueError:
        body = None
    return status, body if isinstance(body, dict) else None


def _refused(status: int, body: dict[str, Any] | None) -> str | None:
    """Why the OAuth server refused the login for good, or None when it may work on another try. A 401 is the client or
    the token being refused, whether or not its body says so."""
    error = body.get("error") if body else None
    if error in REFUSED_GRANTS:
        return str(error)
    return "status 401" if status == 401 else None


def _status(status: int, body: dict[str, Any] | None) -> str:
    return f"status {status}" + ("" if body is not None else ", not JSON")


async def revoke(session: aiohttp.ClientSession, refresh_token: str) -> None:
    """Revokes a refresh token, and with it the login, so it can't renew the access token any more."""
    status, body = await _token_post(
        session,
        REVOKE_URL,
        {"token": refresh_token, "token_type_hint": "refresh_token", "client_id": CLIENT_ID},
        "to revoke the login",
    )
    # A token PostNord no longer knows is answered with 200 as well (RFC 7009).
    if status != 200:
        raise PostNordError(f"PostNord didn't revoke the login ({_status(status, body)}{_why(body)})")


class PostNordLogin:
    """One browser login with PKCE: the link to open, and the exchange of the code it ends with.

    PostNord sends the browser to the app's redirect, which a browser can't open, so the user
    copies it from the developer tools and pastes it back. Anything around the URL (a "Location:"
    label, quotation marks) is tolerated; the code and state are picked out of it.
    """

    def __init__(self) -> None:
        self._verifier = _b64(secrets.token_bytes(64))
        self._state = _b64(secrets.token_bytes(16))

    @property
    def url(self) -> str:
        params = {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "code_challenge": _b64(hashlib.sha256(self._verifier.encode()).digest()),
            "code_challenge_method": "S256",
            "state": self._state,
        }
        return AUTHORIZE_URL + "?" + urlencode(params, quote_via=quote)

    def code_from(self, pasted: str) -> str:
        """The authorization code in the pasted redirect."""
        code = _query_value(pasted, "code")
        if not code:
            raise PostNordRedirectError("no_code")
        if _query_value(pasted, "state") != self._state:
            raise PostNordRedirectError("wrong_state")
        return code

    async def exchange(self, session: aiohttp.ClientSession, pasted: str) -> tuple[str, str]:
        """The access and refresh token for the pasted redirect."""
        code = self.code_from(pasted)
        status, body = await _token_post(
            session,
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "code_verifier": self._verifier,
            },
            "for the login",
        )
        tokens = body or {}
        access_token, refresh_token = tokens.get("access_token"), tokens.get("refresh_token")
        if isinstance(access_token, str) and access_token and isinstance(refresh_token, str) and refresh_token:
            return access_token, refresh_token
        # An expired or already used code is a 400 invalid_grant. Anything else, such as a busy server, is no reason to
        # tell the user their code was wrong.
        if refused := _refused(status, body):
            raise PostNordAuthError(f"PostNord didn't accept the login code ({refused}{_why(body)})")
        raise PostNordError(f"PostNord couldn't complete the login ({_status(status, body)}{_why(body)})")


class PostNordClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        access_token: str,
        refresh_token: str,
        language: str,
        on_new_access_token: Callable[[str], None] | None = None,
    ) -> None:
        self._session = session
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._language = language
        # Called with a refreshed access token, so that it can be saved for the next start.
        self._on_new_access_token = on_new_access_token

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    async def account(self) -> tuple[str, str | None]:
        """The email address of the logged-in account and its subject, from OpenID userinfo."""
        info = await self._get(USERINFO_URL, {}, gateway=False)
        info = info if isinstance(info, dict) else {}
        found = info.get("email") or info.get("preferred_username")
        if not isinstance(found, str) or not found.strip():
            raise PostNordError("PostNord didn't tell the account's email address")
        subject = info.get("sub")
        return found.strip(), str(subject) if subject else None

    async def tracking(self) -> dict[str, Any]:
        """The account's parcels: activeShipments, archivedShipments, deletedShipments.

        summary=true would answer archived parcels with their id and archivedStatus only, without
        events or dates, so the full parcels are asked for.
        """
        data = await self._get(API_BASE_URL + PATH_TRACKING, {"summary": "false"})
        if not isinstance(data, dict) or not all(isinstance(data.get(key), list) for key in SHIPMENT_LISTS):
            raise PostNordError(f"PostNord sent the tracking data without its parcel lists{_why(data)}")
        return data

    async def _get(self, url: str, params: dict[str, str], *, gateway: bool = True) -> Any:
        status, body = await self._fetch(url, params, gateway)
        if status in (401, 403):
            await self._refresh_access_token()
            status, body = await self._fetch(url, params, gateway)
            if status == 401:
                raise PostNordAuthError("PostNord refused the refreshed access token")
            # A fresh token turned away with a 403 is the gateway's doing, such as a changed API key: logging in again
            # wouldn't help, so it is an update that failed, not a login.
            if status == 403:
                raise PostNordError("PostNord's gateway refused the request although the access token is fresh")
        if status != 200:
            raise PostNordError(f"PostNord answered with status {status}")
        return body

    async def _fetch(self, url: str, params: dict[str, str], gateway: bool) -> tuple[int, Any]:
        """A GET with the access token. Calls to the API gateway also carry its key and context."""
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            "Accept-Language": self._language,
            "User-Agent": USER_AGENT,
        }
        if gateway:
            params = {**params, "apikey": API_KEY}
            headers["context"] = CONTEXT
        try:
            async with self._session.get(
                url,
                params=params,
                headers=headers,
                timeout=TIMEOUT,
            ) as response:
                if response.status != 200:
                    return response.status, None
                text = await response.text()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise PostNordError(f"PostNord couldn't be reached: {err}") from err
        try:
            return 200, json.loads(text)
        except ValueError as err:
            raise PostNordError("PostNord answered with something other than JSON") from err

    async def _refresh_access_token(self) -> None:
        status, body = await _token_post(
            self._session,
            TOKEN_URL,
            {"grant_type": "refresh_token", "refresh_token": self._refresh_token, "client_id": CLIENT_ID},
            "for a new access token",
        )
        access_token = (body or {}).get("access_token")
        if not isinstance(access_token, str) or not access_token:
            # Only these say the refresh token is gone. A server error, a 429 or a firewall says nothing about it, and
            # the next update tries again.
            if refused := _refused(status, body):
                raise PostNordAuthError(f"PostNord no longer accepts the refresh token ({refused})")
            raise PostNordError(f"PostNord couldn't refresh the access token ({_status(status, body)}{_why(body)})")

        self._access_token = access_token
        # A rotated refresh token has to replace the old one, or the next refresh fails.
        new_refresh = body.get("refresh_token")
        if isinstance(new_refresh, str) and new_refresh:
            self._refresh_token = new_refresh
        _LOGGER.debug("Refreshed the access token")
        if self._on_new_access_token is not None:
            self._on_new_access_token(access_token)
