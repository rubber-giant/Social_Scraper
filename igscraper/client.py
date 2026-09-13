"""Thin wrapper around the instagrapi private API.

All Instagram network access lives here so the data backend can later be
swapped (e.g. for an Apify actor) without touching the rest of the pipeline.
Login reuses a saved session (session.json) and only re-authenticates when
Instagram rejects it.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Dict, List, Optional

from instagrapi import Client
from instagrapi.exceptions import ChallengeRequired, LoginRequired, PrivateError

from .config import Config

logger = logging.getLogger("igscraper.client")

# instagrapi sleeps ``request_timeout`` before EVERY non-login request
# (private.py: ``time.sleep(self.request_timeout)``), then adds delay_range on
# top. So it is the dominant per-request pacing knob, not the delay_range. It's
# also the real socket timeout. Configurable via settings.request_timeout.
DEFAULT_REQUEST_TIMEOUT = 30


class MissingCredentialsError(Exception):
    """Raised when IG credentials are not configured."""


class InstagramClient:
    def __init__(self, config: Config):
        self.config = config
        self.cl: Optional[Client] = None

    # -- auth ----------------------------------------------------------
    @property
    def _sessionid(self) -> str:
        return os.environ.get("INSTAGRAM_SESSIONID", "").strip()

    def _new_client(self) -> Client:
        cl = Client()
        # Load the saved session FIRST: load_settings() -> init() restores
        # request_timeout (and other knobs) from the session file, so applying
        # our pacing before this point would be silently overwritten.
        session = self.config.session_path
        if session.exists():
            logger.info("Loading saved session from %s", session)
            cl.load_settings(session)
        # Pace requests: Instagram trust-scoring punishes burst traffic.
        base = float(self.config.settings.get("per_request_delay_sec", 3.0))
        jitter = float(self.config.settings.get("request_delay_jitter", 2.0))
        cl.delay_range = [base, base + jitter]
        cl.request_timeout = float(
            self.config.settings.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)
        )
        return cl

    def login(self) -> None:
        """Login with a saved session, sessionid, or username/password.

        Priority:
          1. INSTAGRAM_SESSIONID env var -> trusted existing session (no
             password checkpoint; best for brand-new accounts).
          2. username/password flow (persists a stable device fingerprint even
             when Instagram throws a challenge, so retries look identical).
        """
        if self._sessionid:
            self._login_with_sessionid(self._sessionid)
        else:
            self._login_with_password()

    def _login_with_sessionid(self, sessionid: str) -> None:
        """Reuse an already-authenticated Instagram session (a sessionid cookie).

        This bypasses the password-login checkpoint entirely, which is the
        practical free path for brand-new accounts that Instagram keeps
        challenging. Obtain the value: log into instagram.com in a browser,
        then DevTools -> Application -> Cookies -> instagram.com -> `sessionid`.
        """
        cl = self._new_client()
        session = self.config.session_path
        try:
            cl.login_by_sessionid(sessionid)
        except Exception as exc:  # noqa: BLE001
            try:
                cl.dump_settings(session)
            except Exception:  # noqa: BLE001
                pass
            logger.error(
                "Sessionid login failed (%s: %s). The cookie may be expired, "
                "or Instagram rejected a web session. Get a fresh one and "
                "re-run.",
                type(exc).__name__,
                exc,
            )
            raise
        cl.dump_settings(session)
        logger.info("Login OK via sessionid (session saved to %s)", session)
        self.cl = cl

    def _login_with_password(self) -> None:
        if not self.config.username or not self.config.password:
            raise MissingCredentialsError(
                "No login configured. Either set INSTAGRAM_SESSIONID in .env "
                "(fastest for new accounts) OR set INSTAGRAM_USERNAME and "
                "INSTAGRAM_PASSWORD. Tip: use a dedicated throwaway account."
            )

        cl = self._new_client()
        session = self.config.session_path

        # login() validates a loaded session first; if Instagram rejects it,
        # instagrapi clears the stale state and logs in with credentials.
        logger.info("Logging in as @%s ...", self.config.username)
        # Optional one-time 2FA code can be supplied via INSTAGRAM_2FA_CODE.
        verification_code = os.environ.get("INSTAGRAM_2FA_CODE", "")
        try:
            cl.login(
                self.config.username,
                self.config.password,
                verification_code=verification_code,
            )
        except Exception as exc:  # noqa: BLE001 - persist device on ANY failure
            # Save the randomly generated device fingerprint even when login
            # fails, so a retry after an in-app "This was me" approval presents
            # the SAME device to Instagram instead of a brand-new one each run.
            try:
                cl.dump_settings(session)
            except Exception:  # noqa: BLE001
                pass
            if isinstance(exc, ChallengeRequired):
                logger.error(
                    "Instagram asked for manual verification. Approve this "
                    "login inside the official Instagram app "
                    "(Settings -> Security -> Login activity -> 'This was me') "
                    "or via the email/push Instagram sent, then run again. The "
                    "device fingerprint is now saved in %s so the retry uses "
                    "the same device. Alternatively set INSTAGRAM_SESSIONID to "
                    "skip password login entirely.",
                    session,
                )
            raise
        cl.dump_settings(session)
        logger.info("Login OK (session saved to %s)", session)
        self.cl = cl

    # -- core calls ----------------------------------------------------
    def _call(self, fn: Callable, what: str, *args, **kwargs):
        """Run an API call, mapping expected failures to None with a warning."""
        try:
            return fn(*args, **kwargs)
        except LoginRequired:
            logger.error("Session expired / login required while fetching %s.", what)
            raise
        except PrivateError as exc:
            logger.warning("Instagram error for %s: %s", what, exc)
            return None
        except Exception as exc:  # noqa: BLE001 - surface everything else as warnings
            logger.warning("Unexpected error fetching %s: %s", what, exc)
            return None

    def hashtag_medias(self, tag: str, amount: int, mode: str) -> List:
        """Return media objects posted under ``tag`` (top/recent/both)."""
        cl = self.cl
        if cl is None:
            raise RuntimeError("InstagramClient.login() must be called first.")
        medias: List = []
        if mode in ("top", "both"):
            res = self._call(cl.hashtag_medias_top, f"hashtag #{tag}", tag, amount)
            if res:
                medias += res
        if mode in ("recent", "both"):
            res = self._call(cl.hashtag_medias_recent, f"hashtag #{tag}", tag, amount)
            if res:
                medias += res
        return medias

    def profile(self, username: str) -> Optional[Dict]:
        """Full public profile for a username, normalized to a plain dict."""
        cl = self.cl
        if cl is None:
            raise RuntimeError("InstagramClient.login() must be called first.")
        user = self._call(cl.user_info_by_username, f"profile @{username}", username)
        if user is None:
            return None
        return {
            "pk": user.pk,
            "username": user.username,
            "full_name": user.full_name,
            "biography": user.biography or "",
            "external_url": user.external_url or "",
            "is_business": bool(user.is_business),
            "category": user.business_category_name or user.category or "",
            "public_email": (user.public_email or "").strip(),
            "public_phone": (user.public_phone_number or "").strip(),
            "follower_count": int(user.follower_count or 0),
            "following_count": int(user.following_count or 0),
            "media_count": int(user.media_count or 0),
            "is_verified": bool(user.is_verified),
        }

    def recent_media(self, user_id: str, amount: int) -> List:
        """The most recent ``amount`` media items for a user (for recency + engagement)."""
        cl = self.cl
        if cl is None:
            raise RuntimeError("InstagramClient.login() must be called first.")
        res = self._call(cl.user_medias, f"media of pk {user_id}", user_id, amount)
        return res or []

    # -- discovery surfaces -------------------------------------------
    def search_users(self, query: str, count: int = 30) -> List[Dict]:
        """Accounts matching a keyword query (name / username / bio).

        instagrapi exposes two ``search_users`` methods (a 2-arg one on
        FbSearchMixin and ``search_users_v1(query, count)`` on UserMixin); the
        client's MRO resolves to the 2-arg one, which breaks count control. Prefer
        the versioned, count-capable call and fall back to the 2-arg variant.
        """
        cl = self.cl
        if cl is None:
            raise RuntimeError("InstagramClient.login() must be called first.")
        search_v1 = getattr(cl, "search_users_v1", None)
        if search_v1 is not None:
            users = self._call(search_v1, f"user search '{query}'", query, count)
        else:
            users = self._call(cl.search_users, f"user search '{query}'", query)
        out: List[Dict] = []
        for u in users or []:
            username = getattr(u, "username", "") or ""
            if not username:
                continue
            out.append(
                {
                    "username": username,
                    "pk": str(getattr(u, "pk", "") or ""),
                    "full_name": getattr(u, "full_name", "") or "",
                    "is_verified": bool(getattr(u, "is_verified", False)),
                }
            )
        return out

    def chaining(self, user_id: str) -> List[Dict]:
        """Instagram's "similar accounts" for a user (private API)."""
        cl = self.cl
        if cl is None:
            raise RuntimeError("InstagramClient.login() must be called first.")
        payload = self._call(cl.chaining, f"chaining for pk {user_id}", user_id)
        return _users_from_chaining_payload(payload)

    def related_profiles_gql(self, user_id: str) -> List[Dict]:
        """Related profiles via public GraphQL (fallback for empty chaining)."""
        cl = self.cl
        if cl is None:
            raise RuntimeError("InstagramClient.login() must be called first.")
        users = self._call(
            cl.user_related_profiles_gql, f"related profiles for pk {user_id}", user_id
        )
        out: List[Dict] = []
        for u in users or []:
            username = getattr(u, "username", "") or ""
            if username:
                out.append({"username": username, "pk": str(getattr(u, "pk", "") or "")})
        return out


def _users_from_chaining_payload(payload: Optional[Dict]) -> List[Dict]:
    """Normalize a raw ``discover/chaining/`` response to plain user dicts.

    IG returns the list under ``users`` (app responses have used ``items``);
    parse defensively so a shape change degrades to an empty list.
    """
    if not isinstance(payload, dict):
        return []
    raw = payload.get("users") or payload.get("items") or []
    out: List[Dict] = []
    for u in raw:
        if not isinstance(u, dict):
            continue
        username = u.get("username") or ""
        if not username:
            continue
        out.append(
            {
                "username": username,
                "pk": str(u.get("pk", "") or ""),
                "full_name": u.get("full_name", "") or "",
                "is_verified": bool(u.get("is_verified", False)),
            }
        )
    return out


def pick_authors_from_media(medias: List) -> List[str]:
    """Unique, non-empty usernames from a list of media objects, de-duped."""
    seen = set()
    out = []
    for media in medias:
        username = getattr(getattr(media, "user", None), "username", "") or ""
        if username and username not in seen:
            seen.add(username)
            out.append(username)
    return out
