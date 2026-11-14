"""Small JSON/bytes disk cache used for network responses and derived rasters."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from app.config import settings


class DiskCache:
    def __init__(self, root: Optional[Path] = None, ttl_s: Optional[int] = None) -> None:
        self.root = Path(root or settings.cache_dir)
        self.ttl = ttl_s if ttl_s is not None else settings.cache_ttl_s
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.root / h[:2] / h

    def get_json(self, key: str) -> Optional[Any]:
        raw = self.get_bytes(key)
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def set_json(self, key: str, value: Any) -> None:
        self.set_bytes(key, json.dumps(value, default=str).encode("utf-8"))

    def get_bytes(self, key: str) -> Optional[bytes]:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            if time.time() - p.stat().st_mtime > self.ttl:
                return None
            return p.read_bytes()
        except OSError:
            return None

    def set_bytes(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(p)
        except OSError:
            pass

    def clear(self) -> int:
        n = 0
        for p in self.root.rglob("*"):
            if p.is_file():
                try:
                    p.unlink()
                    n += 1
                except OSError:
                    pass
        return n


cache = DiskCache()
