from __future__ import annotations

from pathlib import Path

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Input, Label, Static

from ..io import load_pool_with_counts, save_pool
from ..pool import MAX_POOL_SIZE, Pool
from ..userdata import data_dir, install_examples
from .card_image import CardImage
from .filepicker import FilePickerScreen
from .widgets import ConfirmScreen


class PoolChanged(Message):
    def __init__(self, pool: Pool) -> None:
        super().__init__()
        self.pool = pool


class PoolLoaded(Message):
    """Posted when the user loads a crypt from disk (distinct from
    in-place edits, which only post PoolChanged). Used by the App to ask
    whether stale rules should be cleared."""

    def __init__(self, pool: Pool) -> None:
        super().__init__()
        self.pool = pool


class PoolReset(Message):
    """Posted when the user clicks "New crypt" to wipe everything.

    The App responds by clearing the rule-set as well so the user starts
    from a blank slate — keeping stale rules around after the crypt is
    reset would only produce "rules reference cards not in crypt" errors.
    """


class PoolPane(VerticalScroll):
    """Edits the crypt — a list of up to 10 named card types."""

    BINDINGS = [
        Binding("ctrl+o", "load", "Load Crypt", priority=True),
        Binding("ctrl+s", "save", "Save Crypt", priority=True),
    ]

    DEFAULT_CSS = """
    PoolPane {
        padding: 1 2;
    }
    PoolPane #pool-grid {
        height: auto;
    }
    PoolPane .pool-row {
        height: 3;
        margin-bottom: 1;
    }
    PoolPane .pool-row CardImage.thumbnail {
        margin: 0 1 0 0;
    }
    PoolPane .pool-row Input.name-input {
        width: 1fr;
        margin-right: 1;
    }
    PoolPane .pool-row Input.count-input {
        width: 10;
        min-width: 10;
        padding: 0 1;
        margin-right: 1;
    }
    PoolPane .pool-row Button.mover {
        min-width: 4;
        width: 4;
        margin: 0;
        padding: 0;
    }
    PoolPane #pool-actions {
        height: auto;
        margin-top: 1;
    }
    PoolPane Button {
        margin-right: 2;
    }
    """

    def __init__(self, pool: Pool, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pool = pool
        self._last_path: Path | None = None

    def compose(self) -> ComposeResult:
        yield Label(
            "[b]Crypt[/b] — up to 10 named cards. These names are used in rules."
        )
        yield Label(
            "Leave the name blank to omit a slot. Names must be unique. "
            "The [b]Count[/b] column defines a [italic]manual deck[/italic] that "
            "the optimizer will evaluate alongside its best picks for comparison."
        )
        yield Label(
            "Reorder rows with the ↑/↓ buttons. The thumbnail previews each "
            "card's art — click it for a large view."
        )
        with Vertical(id="pool-grid"):
            for i in range(MAX_POOL_SIZE):
                default = self._pool.names[i] if i < len(self._pool.names) else ""
                with Horizontal(classes="pool-row", id=f"row-{i}"):
                    yield CardImage(default, classes="thumbnail", id=f"thumb-{i}")
                    yield Input(
                        value=default,
                        placeholder=f"Card {i}",
                        classes="name-input",
                        id=f"pool-slot-{i}",
                    )
                    yield Input(
                        value="",
                        placeholder="#",
                        classes="count-input",
                        id=f"pool-count-{i}",
                        tooltip="Number of copies of this card in the manual deck",
                    )
                    yield Button("↑", id=f"up-{i}", classes="mover")
                    yield Button("↓", id=f"down-{i}", classes="mover")
        with Horizontal(id="pool-actions"):
            yield Button("New crypt", id="pool-new")
            yield Button("Load crypt…", id="pool-load")
            yield Button("Save crypt…", id="pool-save")
            yield Button("Install examples", id="pool-install-examples")
            yield Static("", id="pool-status")

    def _row_values(self) -> list[str]:
        return [
            self.query_one(f"#pool-slot-{i}", Input).value
            for i in range(MAX_POOL_SIZE)
        ]

    def _row_counts(self) -> list[str]:
        return [
            self.query_one(f"#pool-count-{i}", Input).value
            for i in range(MAX_POOL_SIZE)
        ]

    def _set_row_values(self, values: list[str]) -> None:
        for i in range(MAX_POOL_SIZE):
            inp = self.query_one(f"#pool-slot-{i}", Input)
            inp.value = values[i] if i < len(values) else ""

    def _set_row_counts(self, counts: list[str]) -> None:
        for i in range(MAX_POOL_SIZE):
            inp = self.query_one(f"#pool-count-{i}", Input)
            inp.value = counts[i] if i < len(counts) else ""

    def _sync_thumbnails(self) -> None:
        """Re-sync each thumbnail with the name currently in its row."""
        for i in range(MAX_POOL_SIZE):
            name = self.query_one(f"#pool-slot-{i}", Input).value.strip()
            try:
                thumb = self.query_one(f"#thumb-{i}", CardImage)
            except Exception:
                continue
            thumb.set_name(name)

    def _sync_thumbnail(self, i: int) -> None:
        try:
            name = self.query_one(f"#pool-slot-{i}", Input).value.strip()
            self.query_one(f"#thumb-{i}", CardImage).set_name(name)
        except Exception:
            pass

    def collect_counts(self) -> dict[str, int]:
        """Map of card-name -> count entered by the user (omitting blanks / 0s)."""
        names = self._row_values()
        counts = self._row_counts()
        out: dict[str, int] = {}
        for n, c in zip(names, counts):
            n = n.strip()
            c = c.strip()
            if not n or not c:
                continue
            try:
                v = int(c)
            except ValueError:
                continue
            if v > 0:
                out[n] = v
        return out

    def collect(self) -> Pool:
        names = [v.strip() for v in self._row_values()]
        return Pool(names=[n for n in names if n])

    def set_pool(self, pool: Pool, counts: dict[str, int] | None = None) -> None:
        self._pool = pool
        self._set_row_values(list(pool.names))
        if counts is None:
            counts = {}
        # Map each pool slot's count -> the row's count input (blank if 0)
        count_strs: list[str] = []
        for i in range(MAX_POOL_SIZE):
            name = pool.names[i] if i < len(pool.names) else ""
            c = counts.get(name, 0)
            count_strs.append(str(c) if c > 0 else "")
        self._set_row_counts(count_strs)
        # Kick off a fetch for every thumbnail.
        self._sync_thumbnails()

    def _status(self, text: str) -> None:
        self.query_one("#pool-status", Static).update(text)

    def _emit_change(self) -> None:
        try:
            pool = self.collect()
        except ValueError as e:
            self._status(f"[red]{e}[/red]")
            return
        self._status("")
        # Keep self._pool in sync with the freshly-collected names, otherwise
        # any later post_message that reads self._pool (e.g. the count-input
        # handler below) ships a stale empty pool downstream — that broadcast
        # then resets the Rules pane to "no names defined" the moment the user
        # touches a count cell.
        self._pool = pool
        self.post_message(PoolChanged(pool))

    def on_input_changed(self, event: Input.Changed) -> None:
        inp_id = event.input.id or ""
        if inp_id.startswith("pool-slot-"):
            self._emit_change()
        # Count inputs don't affect the Pool model, but trigger an info refresh
        # in case the Run pane wants to reflect the manual-deck total.
        if inp_id.startswith("pool-count-"):
            self.post_message(PoolChanged(self._pool))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter on a name input → update thumbnail + advance focus."""
        inp_id = event.input.id or ""
        if not inp_id.startswith("pool-slot-"):
            return
        try:
            i = int(inp_id.removeprefix("pool-slot-"))
        except ValueError:
            return
        self._sync_thumbnail(i)
        # Advance focus to the next row's name input (if any).
        next_idx = i + 1
        if next_idx < MAX_POOL_SIZE:
            try:
                self.query_one(f"#pool-slot-{next_idx}", Input).focus()
            except Exception:
                pass

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        """Focus leaving a name input → refresh its thumbnail."""
        widget = event.widget
        wid = getattr(widget, "id", None) or ""
        if wid.startswith("pool-slot-"):
            try:
                i = int(wid.removeprefix("pool-slot-"))
            except ValueError:
                return
            self._sync_thumbnail(i)

    def _move(self, i: int, j: int) -> None:
        """Swap row i and row j (name, count and thumbnail travel together)."""
        if i == j or i < 0 or j < 0 or i >= MAX_POOL_SIZE or j >= MAX_POOL_SIZE:
            return
        values = self._row_values()
        counts = self._row_counts()
        values[i], values[j] = values[j], values[i]
        counts[i], counts[j] = counts[j], counts[i]
        self._set_row_values(values)
        self._set_row_counts(counts)
        # Update only the two affected thumbnails.
        self._sync_thumbnail(i)
        self._sync_thumbnail(j)
        self._emit_change()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "pool-new":
            self.action_new()
        elif bid == "pool-load":
            self.action_load()
        elif bid == "pool-save":
            self.action_save()
        elif bid == "pool-install-examples":
            self.action_install_examples()
        elif bid.startswith("up-"):
            i = int(bid.removeprefix("up-"))
            self._move(i, i - 1)
        elif bid.startswith("down-"):
            i = int(bid.removeprefix("down-"))
            self._move(i, i + 1)

    def _default_path(self) -> str:
        if self._last_path is not None:
            return str(self._last_path)
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        return str(d / "untitled.crypt.yaml")

    def action_install_examples(self) -> None:
        """Copy the bundled example crypts + rule-sets into the user's
        data directory. Existing files are preserved so this is safe to
        re-run after the user has edited a previously-installed example.
        """
        try:
            copied = install_examples()
        except OSError as e:
            self._status(f"[red]Install failed: {e}[/red]")
            return
        dest = data_dir()
        if copied:
            self._status(f"Installed {len(copied)} example file(s) to {dest}")
        else:
            self._status(f"Examples already present in {dest}")

    def action_new(self) -> None:
        def on_close(confirmed: bool | None) -> None:
            if not confirmed:
                return
            empty = Pool(names=[])
            self.set_pool(empty, {})
            self._last_path = None
            self._status("New crypt — rules cleared")
            self.post_message(PoolChanged(empty))
            self.post_message(PoolReset())

        self.app.push_screen(
            ConfirmScreen(
                "Reset the crypt to empty and remove all rules? "
                "Any unsaved changes will be lost.",
                title="New crypt",
            ),
            on_close,
        )

    def action_load(self) -> None:
        def on_close(result: Path | None) -> None:
            if result is None:
                return
            try:
                pool, counts = load_pool_with_counts(result)
            except Exception as e:
                self._status(f"[red]Load failed: {e}[/red]")
                return
            self.set_pool(pool, counts)
            self._last_path = result
            self._status(f"Loaded {result}")
            self.post_message(PoolChanged(pool))
            self.post_message(PoolLoaded(pool))

        self.app.push_screen(
            FilePickerScreen(
                mode="load",
                title="Load crypt",
                default_path=self._default_path(),
                kind="crypt",
                must_exist=True,
            ),
            on_close,
        )

    def action_save(self) -> None:
        try:
            pool = self.collect()
        except ValueError as e:
            self._status(f"[red]{e}[/red]")
            return
        counts = self.collect_counts()

        def on_close(result: Path | None) -> None:
            if result is None:
                return
            try:
                save_pool(pool, result, counts)
            except Exception as e:
                self._status(f"[red]Save failed: {e}[/red]")
                return
            self._last_path = result
            self._status(f"Saved to {result}")

        self.app.push_screen(
            FilePickerScreen(
                mode="save",
                title="Save crypt",
                default_path=self._default_path(),
                kind="crypt",
                must_exist=False,
            ),
            on_close,
        )
