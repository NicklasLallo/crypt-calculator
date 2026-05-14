from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from crypt_calculator.screens import cards


def test_card_slug_matrix():
    # krcg drops all non-alphanumerics rather than hyphenating.
    assert cards.card_slug("Anson") == "anson"
    assert cards.card_slug("Black Cat") == "blackcat"
    assert cards.card_slug("Volker, The Puppet Prince") == "volkerthepuppetprince"
    assert cards.card_slug("Gaël Pilet") == "gaelpilet"
    assert (
        cards.card_slug("Céleste, The Voice of a Secret")
        == "celestethevoiceofasecret"
    )
    assert cards.card_slug("  Black Cat  ") == "blackcat"
    assert cards.card_slug("") == ""
    assert cards.card_slug("!!!") == ""


def test_card_slug_leading_the_moves_to_end():
    # krcg moves a leading "The " to the end of the slug.
    assert cards.card_slug("The Unnamed") == "unnamedthe"
    assert cards.card_slug("The Black Cat") == "blackcatthe"
    # Case-insensitive on the prefix.
    assert cards.card_slug("the unnamed") == "unnamedthe"
    assert cards.card_slug("THE Unnamed") == "unnamedthe"
    # Whitespace tolerated.
    assert cards.card_slug("  The Unnamed  ") == "unnamedthe"
    # "The" must be a whole leading word — "Theatre" stays put.
    assert cards.card_slug("Theatre") == "theatre"
    assert cards.card_slug("Theo") == "theo"
    # Inner "The" is left alone — the rule only fires on the leading word.
    assert (
        cards.card_slug("Volker, The Puppet Prince") == "volkerthepuppetprince"
    )


class _StubResponse:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


class _StubClient:
    def __init__(self, responses: list[_StubResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def get(self, url: str, **_kw: object) -> _StubResponse:
        self.calls.append(url)
        return self._responses.pop(0)


def test_fetch_card_image_cache_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cards, "CACHE_DIR", tmp_path)
    client = _StubClient(
        [_StubResponse(200, b"\xff\xd8\xff\xe0FAKEJPEG"),
         _StubResponse(500, b"")]  # second response shouldn't be consumed
    )

    async def run() -> tuple[Path | None, Path | None]:
        first = await cards.fetch_card_image("Anson", http=client)  # type: ignore[arg-type]
        second = await cards.fetch_card_image("Anson", http=client)  # type: ignore[arg-type]
        return first, second

    first, second = asyncio.run(run())
    assert first is not None
    assert first.exists()
    assert first.read_bytes() == b"\xff\xd8\xff\xe0FAKEJPEG"
    assert second == first
    assert len(client.calls) == 1, "second call must hit the cache"


def test_fetch_card_image_404(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cards, "CACHE_DIR", tmp_path)
    client = _StubClient([_StubResponse(404, b"")])

    async def run() -> Path | None:
        return await cards.fetch_card_image("Nonsuch", http=client)  # type: ignore[arg-type]

    result = asyncio.run(run())
    assert result is None
    assert not list(tmp_path.glob("*.jpg")), "404 must not write a cache file"
    # A miss sentinel should record the 404 so we don't refetch.
    misses = list(tmp_path.glob("*.miss"))
    assert len(misses) == 1
    assert misses[0].name == "nonsuch.miss"


def test_fetch_card_image_404_negative_cache_skips_refetch(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(cards, "CACHE_DIR", tmp_path)
    # Only one 404 response is queued. A second fetch must NOT consume
    # another response — it must short-circuit on the miss sentinel.
    client = _StubClient([_StubResponse(404, b"")])

    async def run() -> tuple[Path | None, Path | None]:
        first = await cards.fetch_card_image("Nonsuch", http=client)  # type: ignore[arg-type]
        second = await cards.fetch_card_image("Nonsuch", http=client)  # type: ignore[arg-type]
        return first, second

    first, second = asyncio.run(run())
    assert first is None
    assert second is None
    assert len(client.calls) == 1, "second call must hit the miss sentinel"


def test_fetch_card_image_network_error_does_not_cache_miss(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(cards, "CACHE_DIR", tmp_path)

    class _RaisingClient:
        def __init__(self) -> None:
            self.calls = 0

        async def get(self, url: str, **_kw: object):
            self.calls += 1
            raise httpx.ConnectError("boom")

    client = _RaisingClient()

    async def run() -> tuple[Path | None, Path | None]:
        a = await cards.fetch_card_image("Anson", http=client)  # type: ignore[arg-type]
        b = await cards.fetch_card_image("Anson", http=client)  # type: ignore[arg-type]
        return a, b

    a, b = asyncio.run(run())
    assert a is None
    assert b is None
    # Transient errors should NOT poison the cache — both attempts must hit
    # the network so a later successful fetch can fill the cache.
    assert client.calls == 2
    assert not list(tmp_path.glob("*.miss"))


def test_fetch_card_image_empty_name(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cards, "CACHE_DIR", tmp_path)
    client = _StubClient([])

    async def run() -> Path | None:
        return await cards.fetch_card_image("", http=client)  # type: ignore[arg-type]

    assert asyncio.run(run()) is None
    assert client.calls == []
