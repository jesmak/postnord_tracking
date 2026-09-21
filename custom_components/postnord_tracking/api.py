"""PostNord's app API: the account's parcels, active and archived.

Requests carry the OAuth access token of a PostNord login. When it has expired, the refresh
token gets a new one. When that fails too, the account has to be logged in again (`PostNordLogin`,
driven by the config flow). The gateway's subscription key rides in the query string, and every
call sends the app's context header.
"""

from __future__ import annotations

import base64
import hashlib
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
    SCOPES,
    TOKEN_URL,
    USER_AGENT,
    USERINFO_URL,
)

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=20)


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
        try:
            async with session.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                    "client_id": CLIENT_ID,
                    "code_verifier": self._verifier,
                },
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=TIMEOUT,
            ) as response:
                status = response.status
                body = await response.json(content_type=None) if status < 500 else None
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise PostNordError(f"PostNord couldn't be reached for the login: {err}") from err

        if status >= 500:
            raise PostNordError(f"PostNord couldn't complete the login (status {status})")
        tokens = body if isinstance(body, dict) else {}
        access_token, refresh_token = tokens.get("access_token"), tokens.get("refresh_token")
        # An expired or already used code is a 400 invalid_grant.
        if not (isinstance(access_token, str) and access_token and isinstance(refresh_token, str) and refresh_token):
            raise PostNordAuthError(f"PostNord didn't accept the login code (status {status})")
        return access_token, refresh_token


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

    async def email(self) -> str:
        """The email address of the logged-in account, from OpenID userinfo."""
        info = await self._get(USERINFO_URL, {}, gateway=False)
        info = info if isinstance(info, dict) else {}
        found = info.get("email") or info.get("username")
        if not isinstance(found, str) or not found.strip():
            raise PostNordError("PostNord didn't tell the account's email address")
        return found.strip()

    async def tracking(self) -> dict[str, Any]:
        """The account's parcels: activeShipments, archivedShipments, deletedShipments.

        summary=true would answer archived parcels with their id and archivedStatus only, without
        events or dates, so the full parcels are asked for.
        """
        data = await self._get(API_BASE_URL + PATH_TRACKING, {"summary": "false"})
        if not isinstance(data, dict):
            raise PostNordError("PostNord sent the tracking data in an unexpected format")
        return data

    async def _get(self, url: str, params: dict[str, str], *, gateway: bool = True) -> Any:
        status, body = await self._fetch(url, params, gateway)
        if status in (401, 403):
            await self._refresh_access_token()
            status, body = await self._fetch(url, params, gateway)
            if status in (401, 403):
                raise PostNordAuthError("PostNord refused the refreshed access token")
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
                return response.status, await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise PostNordError(f"PostNord couldn't be reached: {err}") from err

    async def _refresh_access_token(self) -> None:
        try:
            async with self._session.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id": CLIENT_ID,
                },
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=TIMEOUT,
            ) as response:
                status = response.status
                body = await response.json(content_type=None) if status < 500 else None
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise PostNordError(f"PostNord couldn't be reached for a new access token: {err}") from err

        # A server error says nothing about the token: try again at the next update.
        if status >= 500:
            raise PostNordError(f"PostNord couldn't refresh the access token (status {status})")
        access_token = body.get("access_token") if isinstance(body, dict) else None
        if not isinstance(access_token, str) or not access_token:
            raise PostNordAuthError("PostNord didn't give a new access token")

        self._access_token = access_token
        # A rotated refresh token has to replace the old one, or the next refresh fails.
        new_refresh = body.get("refresh_token")
        if isinstance(new_refresh, str) and new_refresh:
            self._refresh_token = new_refresh
        _LOGGER.debug("Refreshed the access token")
        if self._on_new_access_token is not None:
            self._on_new_access_token(access_token)
