"""Earthdata Login (URS) support for authenticated NASA downloads.

Configuration (server side only — never sent to the browser):

    EARTHDATA_TOKEN      <- preferred: a personal URS bearer token
    EARTHDATA_USERNAME   \
    EARTHDATA_PASSWORD   / alternatively username+password (form login flow)

Without credentials TerraTrace still performs full *metadata* discovery through
CMR; only raster/HDF5 downloads of NASA science products are blocked, and the
API reports that honestly (`requires_credentials: true`).
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Optional

import requests

from app.config import settings
from app.core.logging import get_logger

log = get_logger("data_sources.earthdata")

URS = "https://urs.earthdata.nasa.gov"
URS_LOGIN = f"{URS}/login"
TOKEN_ENDPOINT = f"{URS}/oauth/token"
# Public client id used by common NASA open-source download clients.
CLIENT_ID = "BO_n7nTIlMljdvU6kRRB3g"


def is_configured() -> bool:
    return settings.earthdata_configured


class EarthdataSession:
    """Session with Bearer token or interactive URS form login (cached)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: Optional[requests.Session] = None

    # ------------------------------------------------------------------ build
    def _build(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({"User-Agent": settings.user_agent})
        if settings.earthdata_token:
            s.headers["Authorization"] = f"Bearer {settings.earthdata_token}"
            return s
        if settings.earthdata_username and settings.earthdata_password:
            if not self._urs_login(s):
                # last resort: HTTP basic (works for providers that accept it directly)
                s.auth = (settings.earthdata_username, settings.earthdata_password)
        return s

    def _urs_login(self, s: requests.Session) -> bool:
        try:
            page = s.get(URS_LOGIN, timeout=settings.http_timeout_s)
            token = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', page.text)
            payload = {
                "username": settings.earthdata_username,
                "password": settings.earthdata_password,
                "authenticity_token": token.group(1) if token else "",
                "client_id": CLIENT_ID,
                "redirect_uri": s.headers.get("Referer") or URS_LOGIN,
                "response_type": "code",
                "scope": "organization",
            }
            resp = s.post(URS_LOGIN, data=payload, timeout=settings.http_timeout_s)
            ok = "Data Loader" in resp.text or "logout" in resp.text.lower()
            if ok:
                log.info("Earthdata Login form session established")
            return ok
        except requests.RequestException as exc:
            log.warning("Earthdata Login form flow failed", extra={"extra_fields": {"error": str(exc)}})
            return False

    @property
    def session(self) -> requests.Session:
        with self._lock:
            if self._session is None:
                self._session = self._build()
            return self._session

    def reset(self) -> None:
        with self._lock:
            self._session = None


earthdata_session = EarthdataSession()


def auth_available() -> bool:
    return is_configured()


def download(
    url: str,
    dest: Path,
    *,
    max_mb: Optional[int] = None,
    allow_redirects: bool = True,
) -> Path:
    """Bounded, authenticated download of a NASA science product."""
    if not is_configured():
        raise PermissionError(
            "Earthdata Login credentials are not configured. Set EARTHDATA_TOKEN (or "
            "EARTHDATA_USERNAME/EARTHDATA_PASSWORD) in backend/.env to download this product."
        )
    limit = (max_mb or settings.max_download_mb) * 1024 * 1024
    dest.parent.mkdir(parents=True, exist_ok=True)
    with earthdata_session.session.get(url, stream=True, timeout=120, allow_redirects=allow_redirects) as resp:
        if resp.status_code in (401, 403):
            raise PermissionError(
                f"Authenticated request rejected (HTTP {resp.status_code}) for {url[:120]}. "
                "Check EARTHDATA_TOKEN / username / password."
            )
        resp.raise_for_status()
        written = 0
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                written += len(chunk)
                if written > limit:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise OverflowError(
                        f"Refusing to download more than {limit // (1024 * 1024)} MB (bounded download)."
                    )
                fh.write(chunk)
    return dest
