"""Card-art widget + zoom modal.

``CardImage`` is a container with two children — an AutoImage and a Static
placeholder — and toggles their ``display`` based on whether the image has
loaded. Both children are mounted once in compose; we never unmount/remount
inside the widget's lifetime, so there's no race between fetch completion
and widget tree updates.

The placeholder is always present and shows fetch state ("…" while fetching,
"(no art)" on failure). If the image renders successfully it covers the
placeholder; if it doesn't, the user at least sees the text status.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from textual import events, work
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static
from textual_image.widget import (
    AutoImage,
    HalfcellImage,
    SixelImage,
    TGPImage,
    UnicodeImage,
)

from . import cards
from .widgets import DismissOnOutsideClickMixin


# textual-image probes the terminal for graphics support at import time
# and picks one of TGP / sixel / halfcell / unicode. Inside a terminal
# multiplexer (tmux / zellij / screen) the probe sees the multiplexer's
# emulated terminal — which typically advertises sixel without actually
# forwarding graphics escapes to the host terminal, so AutoImage emits
# sixel data that disappears into the void.
#
# We auto-fall-back to halfcell when we detect a multiplexer wrapper.
# CRYPT_CALCULATOR_RENDERER lets users force a specific renderer either
# to opt back into auto-detection in a passthrough-configured multiplexer
# or to work around any other misdetection.
_RENDERER_OVERRIDES = {
    "auto": AutoImage,
    "tgp": TGPImage,
    "kitty": TGPImage,
    "sixel": SixelImage,
    "halfcell": HalfcellImage,
    "unicode": UnicodeImage,
}


def _in_multiplexer() -> bool:
    return any(os.environ.get(v) for v in ("TMUX", "ZELLIJ", "STY"))


def _select_image_widget() -> type:
    override = os.environ.get("CRYPT_CALCULATOR_RENDERER", "").strip().lower()
    if override in _RENDERER_OVERRIDES:
        return _RENDERER_OVERRIDES[override]
    if _in_multiplexer():
        return HalfcellImage
    return AutoImage


ImageWidget = _select_image_widget()


class CardImage(Container):
    """One card's art, fetched lazily by name. Click to zoom."""

    DEFAULT_CSS = """
    CardImage {
        background: transparent;
    }
    CardImage.thumbnail {
        width: 5;
        height: 3;
        min-width: 5;
        min-height: 3;
    }
    CardImage.standard {
        width: 17;
        height: 12;
        min-width: 17;
        min-height: 12;
    }
    CardImage #card-img {
        width: 100%;
        height: 100%;
        background: transparent;
    }
    CardImage Static.cardimage-placeholder {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: $text-muted;
        background: transparent;
    }
    """

    def __init__(self, name: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._name: str = name

    def compose(self) -> ComposeResult:
        # Both children are always mounted; we toggle `display` to swap.
        yield ImageWidget(image=None, id="card-img")
        yield Static("", id="card-placeholder", classes="cardimage-placeholder")

    def on_mount(self) -> None:
        self._refresh_for_name()

    @property
    def card_name(self) -> str:
        return self._name

    def set_name(self, name: str) -> None:
        name = (name or "").strip()
        if name == self._name:
            return
        self._name = name
        if not self.is_mounted:
            return
        self._refresh_for_name()

    def _refresh_for_name(self) -> None:
        """Render whatever we can synchronously, only kicking off a worker
        when the disk cache hasn't already answered the question.

        Without this short-circuit, every mount of a CardImage spawns a
        @work fetch — and when CardArtPanel rebuilds the grid (e.g. on the
        first resize after the Results tab is shown), those in-flight
        workers are cancelled with the widget. New widgets then start fresh
        workers, and if rebuilds keep pace with fetches the placeholder
        never gets replaced.
        """
        if not self._name:
            self._show_placeholder("")
            return
        cached = cards.cache_path_for(self._name)
        if cached is not None and cached.exists():
            self._show_image(cached)
            return
        miss = cards.miss_path_for(self._name)
        if miss is not None and miss.exists():
            self._show_placeholder("(no art)")
            return
        self._show_placeholder("…")
        self._kickoff_fetch()

    # ── internal display state ──────────────────────────────────────────────

    def _img(self) -> ImageWidget:
        return self.query_one("#card-img", ImageWidget)

    def _ph(self) -> Static:
        return self.query_one("#card-placeholder", Static)

    def _show_placeholder(self, text: str) -> None:
        try:
            img = self._img()
            ph = self._ph()
        except Exception:
            return
        ph.update(text)
        # Clear any previous image so it doesn't leak across name changes.
        try:
            img.image = None
        except Exception:
            pass
        img.display = False
        ph.display = True

    def _show_image(self, path: Path) -> None:
        try:
            img = self._img()
            ph = self._ph()
        except Exception:
            return
        try:
            img.image = str(path)
        except Exception:
            self._show_placeholder("(no art)")
            return
        ph.display = False
        img.display = True

    # ── fetch ───────────────────────────────────────────────────────────────

    @work(group="card-fetch")
    async def _kickoff_fetch(self) -> None:
        target_name = self._name
        async with httpx.AsyncClient() as client:
            path: Path | None = await cards.fetch_card_image(target_name, http=client)
        if not self.is_mounted or self._name != target_name:
            return
        if path is None:
            self._show_placeholder("(no art)")
            return
        self._show_image(path)

    # ── click → zoom ────────────────────────────────────────────────────────

    def on_click(self, event: events.Click) -> None:
        if not self._name:
            return
        path = cards.cache_path_for(self._name)
        if path is None or not path.exists():
            return
        self.app.push_screen(ZoomedCardScreen(self._name, path))


class ZoomedCardScreen(DismissOnOutsideClickMixin, ModalScreen[None]):
    """Big-image preview of one card. Click outside or Escape dismisses."""

    DEFAULT_CSS = """
    ZoomedCardScreen { align: center middle; }
    ZoomedCardScreen #zoom-container {
        width: auto;
        height: auto;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
    }
    ZoomedCardScreen Label {
        margin-bottom: 1;
    }
    ZoomedCardScreen #zoom-img {
        /* 63:88 card aspect at ~2:1 cell aspect:
           width_cells = height_cells × 2 × 63/88, so 32 lines → ~46 cells. */
        width: 46;
        height: 32;
        min-width: 46;
        min-height: 32;
    }
    """

    BINDINGS = [("escape", "cancel", "Close")]

    def __init__(self, name: str, image_path: Path) -> None:
        super().__init__()
        self._name = name
        self._image_path = image_path

    def compose(self) -> ComposeResult:
        with Vertical(id="zoom-container"):
            yield Static(f"[b]{self._name}[/]")
            yield ImageWidget(str(self._image_path), id="zoom-img")

    def action_cancel(self) -> None:
        self.dismiss(None)
