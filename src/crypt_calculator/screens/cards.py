"""Card-name -> krcg URL slug, plus an async fetcher with on-disk cache.

The art lives at ``https://static.krcg.org/card/<slug>.jpg``. The slug rule
(verified against krcg) is:

- if the name starts with a leading "The " token, move it to the end
  ("The Unnamed" -> "Unnamed The" -> "unnamedthe")
- NFKD-normalise (so combining marks separate from their base letter)
- strip combining marks (accents drop: "Cele" + accent -> "Cele")
- lowercase
- **delete** every non-alphanumeric character (no hyphenation, no separator)

Examples:
  "Anson"                      -> "anson"
  "Black Cat"                  -> "blackcat"
  "The Unnamed"                -> "unnamedthe"
  "Volker, The Puppet Prince"  -> "volkerthepuppetprince"
  "Gael Pilet" (with accent)   -> "gaelpilet"

The cache lives in the platform's user-cache directory under a
``cards/`` subfolder (resolved via :mod:`platformdirs`). Successful
fetches write ``<slug>.jpg``; 404s write a zero-byte ``<slug>.miss``
sentinel so we don't re-hit krcg for names it doesn't have art for.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

import platformdirs

from ..userdata import APP_NAME

if TYPE_CHECKING:
    import httpx

CACHE_DIR = platformdirs.user_cache_path(APP_NAME, appauthor=False) / "cards"
CARD_URL_TEMPLATE = "https://static.krcg.org/card/{slug}.jpg"


def card_slug(name: str) -> str:
    """Normalise a card name into its krcg URL slug."""
    if not name:
        return ""
    text = name.strip()
    # krcg convention: a leading "The " is moved to the end, so
    # "The Unnamed" becomes "Unnamed The" → "unnamedthe". Only applies
    # when "The" is a whole leading word (not the start of "Theatre" etc.).
    m = re.match(r"^the\s+(.+)$", text, re.IGNORECASE)
    if m:
        text = f"{m.group(1)} The"
    # NFKD splits accents into separate combining characters we then drop.
    decomposed = unicodedata.normalize("NFKD", text)
    no_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    # Delete everything that isn't ASCII alphanumeric.
    slug = re.sub(r"[^a-zA-Z0-9]+", "", no_marks)
    return slug.lower()


def cache_path_for(name: str) -> Path | None:
    slug = card_slug(name)
    if not slug:
        return None
    return CACHE_DIR / f"{slug}.jpg"


def miss_path_for(name: str) -> Path | None:
    """Sentinel path used to remember that krcg has no art for ``name``."""
    slug = card_slug(name)
    if not slug:
        return None
    return CACHE_DIR / f"{slug}.miss"


async def fetch_card_image(
    name: str, *, http: "httpx.AsyncClient"
) -> Path | None:
    """Return the local cached JPG path for ``name``'s art.

    Behaviour:
    - empty / blank name → ``None``, no HTTP call.
    - cached JPG already on disk → return its path, no HTTP call.
    - cached miss-sentinel already on disk → return ``None``, no HTTP call.
    - otherwise fetch from krcg. On HTTP 200 write the JPG atomically.
      On HTTP 404 write a miss-sentinel so we won't refetch next time.
      On any other failure (network, transient 5xx) return ``None`` but
      record nothing — we'll retry on the next call.
    """
    target = cache_path_for(name)
    miss = miss_path_for(name)
    if target is None or miss is None:
        return None
    if target.exists():
        return target
    if miss.exists():
        return None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        url = CARD_URL_TEMPLATE.format(slug=card_slug(name))
        response = await http.get(url, timeout=10.0, follow_redirects=True)
    except Exception:
        return None
    if response.status_code == 404:
        try:
            miss.touch()
        except OSError:
            pass
        return None
    if response.status_code != 200 or not response.content:
        return None
    # Atomic write: temp file, then rename.
    tmp = target.with_suffix(".jpg.part")
    tmp.write_bytes(response.content)
    tmp.replace(target)
    return target
