#!/usr/bin/env python3
"""pnpaste.py — PostNord login by hand, no scheme handler, sandbox-proof.

    python3 pnpaste.py

Prints the authorize URL. Open it, but FIRST open your browser's DevTools (F12) > Network tab
and tick "Preserve log". Log in. Among the requests, the last one to account.postnord.com
returns a redirect whose Location is  com.postnord.app://redirect?code=...&state=...  — copy
that whole value and paste it here. Works in any browser on any OS, even a Flatpak/sandboxed one.
"""

import base64
import hashlib
import json
import os
import secrets
import tempfile
import urllib.error
import urllib.parse
import urllib.request

CLIENT_ID = "receiverappprod3gvTgY5ATtYWZZy"
REDIRECT = "com.postnord.app://redirect"
AUTHORIZE = "https://account.postnord.com/auth"
TOKEN = "https://account.postnord.com/oauth2/token"
SCOPE = " ".join(
    [
        "openid",
        "offline_access",
        "https://api.postnord.com/scopes/shipment/eventsorterservice/recipient",
        "https://api.postnord.com/scopes/receiverapp-bff/track",
        "https://api.postnord.com/scopes/trackedshipments/track",
        "https://api.postnord.com/scopes/recipientinstructions/read",
        "https://api.postnord.com/scopes/eta/livetracking",
        "https://api.postnord.com/scopes/preferences/recipient",
    ]
)
UA = "okhttp/4.12.0"


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def main() -> None:
    verifier = b64(secrets.token_bytes(64))
    challenge = b64(hashlib.sha256(verifier.encode()).digest())
    state = b64(secrets.token_bytes(16))

    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    url = AUTHORIZE + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    print("Open DevTools (F12) > Network, tick 'Preserve log', THEN open this and log in:\n")
    print(url + "\n")
    print("Copy the com.postnord.app://redirect?... URL (the redirect's Location) and paste it.\n")

    pasted = input("URL: ").strip()
    fields = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
    if fields.get("state", [None])[0] not in (None, state):
        print("State mismatch:", fields)
        return
    code = fields.get("code", [None])[0]
    if not code:
        print("No ?code= in that URL:", fields)
        return

    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
        }
    ).encode()
    req = urllib.request.Request(
        TOKEN,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": UA,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as err:
        print("Token exchange failed:", err.code)
        print(err.read().decode(errors="replace")[:800])
        return

    for key in ("access_token", "refresh_token", "id_token"):
        val = payload.get(key)
        print(f"{key}: {val[:40] + '...' if val else '(missing)'}")
    print("expires_in:", payload.get("expires_in"))
    out = os.path.join(tempfile.gettempdir(), "pn_tokens.json")
    with open(out, "w") as handle:
        json.dump(payload, handle, indent=2)
    print(f"\nFull response written to {out}")


if __name__ == "__main__":
    main()
