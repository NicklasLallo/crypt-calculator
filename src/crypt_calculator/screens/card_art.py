"""CardArtPanel — bottom-of-Results card display.

Lays out card images in rows that wrap to the panel width. Identical
copies cluster (pool order, repeated by count).

Layout uses **two Horizontal rows per "logical" row**: one of CardImage
widgets, then one of Static labels beneath them. This avoids wrapping
each image in its own Container — that wrapper used to fight the
Kitty / iTerm / Sixel graphics protocols and prevented the actual
image bytes from making it to the terminal (the placeholder Statics
inside rendered fine, but AutoImage did not).
"""

from __future__ import annotations

from typing import Mapping

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from ..pool import Pool
from .card_image import CardImage

# Slot dimensions — must match CardImage.standard CSS.
_CARD_W = 17
_LABEL_W = _CARD_W + 1  # image + margin
_PANEL_H_PAD = 4
_H_GAP = 1


class CardArtPanel(Vertical):
    """Card-art panel below the Results comparison."""

    DEFAULT_CSS = """
    CardArtPanel {
        height: auto;
        border: round $accent;
        padding: 1 2;
        margin-top: 1;
    }
    CardArtPanel #card-art-header {
        height: auto;
        margin-bottom: 1;
    }
    CardArtPanel #card-art-grid {
        height: auto;
    }
    CardArtPanel .card-art-img-row {
        height: 12;
    }
    CardArtPanel .card-art-img-row CardImage {
        margin-right: 1;
    }
    CardArtPanel .card-art-label-row {
        height: 1;
        margin-bottom: 1;
    }
    CardArtPanel .card-label {
        width: 18;
        content-align: center top;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sequence: list[str] = []
        # Track last-rendered column count so on_resize only rebuilds when
        # the layout actually needs to change. Without this guard, every
        # mount/unmount triggered by _rebuild_grid causes another Resize,
        # which causes another rebuild, which cancels the @work fetches
        # of the CardImages we just mounted — and they end up stuck on
        # their loading placeholder.
        self._last_cols: int = -1

    def compose(self) -> ComposeResult:
        yield Static(
            "[b]Crypt[/]  [dim](Run the optimizer to see card art for the selected deck.)[/]",
            id="card-art-header",
        )
        yield Vertical(id="card-art-grid")

    def show_deck(
        self,
        *,
        name_to_count: Mapping[str, int],
        pool: Pool,
        deck_label: str,
    ) -> None:
        """Expand counts into the ordered sequence, then lay out the grid."""
        seq: list[str] = []
        for name in pool.names:
            for _ in range(name_to_count.get(name, 0)):
                seq.append(name)
        for name, c in name_to_count.items():
            if name not in pool.names:
                seq.extend([name] * c)
        total = len(seq)
        suffix = "card" if total == 1 else "cards"
        self.query_one("#card-art-header", Static).update(
            f"[b]Crypt[/] — showing [b]{deck_label}[/] ({total} {suffix})"
        )
        # Skip the rebuild if the deck is identical to what's already on
        # screen — show_deck gets called several times in rapid succession
        # (once from the explicit refresh at the end of show_results, again
        # from each TabActivated as panes are added), and each rebuild
        # cancels every CardImage's in-flight fetch worker.
        if seq == self._sequence:
            return
        self._sequence = seq
        self._rebuild_grid()

    def on_resize(self, event: events.Resize) -> None:
        if not self._sequence:
            return
        new_cols = self._columns()
        if new_cols == self._last_cols:
            # No structural change — don't churn the children, otherwise
            # CardImage @work fetches get cancelled by the unmount.
            return
        self._rebuild_grid()

    def _columns(self) -> int:
        width = self.content_size.width or self.size.width or 100
        slot_w = _CARD_W + _H_GAP
        return max(1, (width - _PANEL_H_PAD) // slot_w)

    def _rebuild_grid(self) -> None:
        grid = self.query_one("#card-art-grid", Vertical)
        for child in list(grid.children):
            child.remove()
        if not self._sequence:
            self._last_cols = -1
            return
        cols = self._columns()
        self._last_cols = cols
        for row_start in range(0, len(self._sequence), cols):
            row_cards = self._sequence[row_start : row_start + cols]
            # First row: card images
            img_row = Horizontal(classes="card-art-img-row")
            grid.mount(img_row)
            for name in row_cards:
                img_row.mount(CardImage(name, classes="standard"))
            # Second row: labels below
            label_row = Horizontal(classes="card-art-label-row")
            grid.mount(label_row)
            for name in row_cards:
                label_row.mount(Static(name, classes="card-label"))
