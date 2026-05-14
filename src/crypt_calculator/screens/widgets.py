from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RadioButton as _StockRadioButton
from textual.widgets import Static

from ..rules import Bucket

# Single source of truth for bucket colours, used by every UI surface
# that mentions a bucket (Rules, Run, Results) so the palette stays
# consistent. A smooth, subdued green→red gradient — saturations under
# ~50% so the text reads cleanly on the dark background.
BUCKET_COLORS: dict[Bucket, str] = {
    "perfect": "#6FB36A",       # muted forest green
    "good": "#A8C46A",          # yellow-green
    "acceptable": "#D7A968",    # muted amber
    "unacceptable": "#C46A66",  # dusty red
}


def colored_bucket(bucket: Bucket, *, bold: bool = False) -> str:
    """Return Rich markup for ``bucket`` styled with the bucket palette.

    Example: ``colored_bucket("perfect")`` → ``"[#6FB36A]Perfect[/]"``.
    """
    color = BUCKET_COLORS[bucket]
    body = bucket.capitalize()
    if bold:
        body = f"[b]{body}[/b]"
    return f"[{color}]{body}[/]"


class RadioButton(_StockRadioButton):
    """Same as textual.widgets.RadioButton but with a narrow inner glyph.

    The stock glyph (`●` U+25CF) is East-Asian-Width "Ambiguous" — some
    terminals render it 2 cells wide, breaking the `▐X▌` alignment. Use the
    same letter glyph that ToggleButton uses by default.
    """

    BUTTON_INNER = "X"


class DismissOnOutsideClickMixin:
    """Mixin for ModalScreen: clicks on the dimmed backdrop dismiss with None."""

    def on_click(self, event: events.Click) -> None:  # type: ignore[override]
        # ``event.widget`` is the actual widget that received the click. For a
        # click on the dim backdrop the screen itself is the recipient.
        if event.widget is self:
            assert isinstance(self, ModalScreen)
            self.dismiss(None)


class ConfirmScreen(DismissOnOutsideClickMixin, ModalScreen[bool]):
    """Simple yes/no confirm dialog.

    Returns ``True`` on Yes, ``False`` on No / Escape / outside click.
    """

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    ConfirmScreen #container {
        width: 70;
        height: auto;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
    }
    ConfirmScreen #message {
        height: auto;
        margin-bottom: 1;
    }
    ConfirmScreen .actions {
        height: 3;
    }
    ConfirmScreen Button {
        margin-right: 1;
        min-width: 12;
    }
    """

    BINDINGS = [
        Binding("y", "yes", "Yes", priority=True),
        Binding("n", "no", "No", priority=True),
        Binding("escape", "no", "Cancel", priority=True),
    ]

    def __init__(self, message: str, *, title: str = "Confirm") -> None:
        super().__init__()
        self._title = title
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="container"):
            yield Label(f"[b]{self._title}[/b]")
            yield Static(self._message, id="message")
            with Horizontal(classes="actions"):
                yield Button("[u]Y[/u]es", id="yes", variant="primary")
                yield Button("[u]N[/u]o", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        elif event.button.id == "no":
            self.dismiss(False)

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)
