"""Modal file picker with a fuzzy-finder UI.

On open the picker:
- Scans a single directory (default ``examples/``) for files whose name
  ends in the kind-specific suffix (``.crypt.yaml`` or ``.rules.yaml``).
- Shows them in a `ListView`, sorted alphabetically.
- Focuses an `Input`. Typing filters the list in real time using a
  case-insensitive subsequence match, sorted by score.
- ``Enter`` commits the currently-highlighted item (or, in save mode,
  the typed filename appended with the kind suffix if missing).
- ``Esc`` or click-outside cancels.

The `kind` parameter ("crypt", "rules", or "any") controls both the
extension filter and what suffix is auto-appended to a save filename.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

from .widgets import DismissOnOutsideClickMixin


Kind = Literal["crypt", "rules", "any"]

_EXT_FOR_KIND: dict[Kind, str] = {
    "crypt": ".crypt.yaml",
    "rules": ".rules.yaml",
    "any": ".yaml",
}


def fuzzy_match(
    query: str, candidate: str
) -> tuple[int, list[int]] | None:
    """Subsequence fuzzy match (case-insensitive).

    Returns ``(score, positions)`` if every char of ``query`` appears in
    order somewhere in ``candidate``; ``None`` otherwise. ``positions`` is
    the list of character indices in ``candidate`` that matched, useful for
    highlighting the match in the UI.

    Scoring rewards consecutive matches and matches at word boundaries
    (after ``_``, ``-``, ``.``, space, or at the start) so "ac" against
    "anson_crypt" scores highly via word-boundary hits on a/c. Shorter
    candidates rank higher when scores tie.
    """
    if not query:
        return (0, [])
    q = query.lower()
    c = candidate.lower()
    qi = 0
    score = 0
    positions: list[int] = []
    last_idx = -2
    for i, ch in enumerate(c):
        if qi >= len(q):
            break
        if ch == q[qi]:
            if i == last_idx + 1:
                score += 5  # consecutive
            elif i == 0 or not c[i - 1].isalnum():
                score += 4  # word-boundary
            else:
                score += 1  # plain match
            last_idx = i
            qi += 1
            positions.append(i)
    if qi < len(q):
        return None
    # Prefer shorter candidates when scores tie.
    return score * 100 - len(c), positions


def fuzzy_score(query: str, candidate: str) -> int | None:
    """Thin wrapper around :func:`fuzzy_match` returning just the score."""
    m = fuzzy_match(query, candidate)
    return None if m is None else m[0]


def _highlight_matches(text: str, positions: list[int]) -> str:
    """Return a Rich-markup string with characters at ``positions`` wrapped
    in [yellow]…[/yellow]. Consecutive positions are merged into a single
    span for cleaner output and fewer markup tags."""
    if not positions:
        # Escape any literal "[" so Rich doesn't try to parse markup we
        # didn't put there.
        return text.replace("[", "\\[")
    pos_set = set(positions)
    parts: list[str] = []
    in_match = False
    for i, ch in enumerate(text):
        is_match = i in pos_set
        if is_match and not in_match:
            parts.append("[yellow]")
            in_match = True
        elif not is_match and in_match:
            parts.append("[/yellow]")
            in_match = False
        # Escape stray '[' so it isn't interpreted as markup.
        parts.append("\\[" if ch == "[" else ch)
    if in_match:
        parts.append("[/yellow]")
    return "".join(parts)


class FilePickerScreen(DismissOnOutsideClickMixin, ModalScreen[Path | None]):
    DEFAULT_CSS = """
    FilePickerScreen { align: center middle; }
    FilePickerScreen #container {
        width: 80;
        height: 80%;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
    }
    FilePickerScreen Input {
        margin: 1 0;
    }
    FilePickerScreen ListView {
        height: 1fr;
        border: round $accent;
    }
    /* Make the current selection visible even when the search Input is
       focused (default ListView only highlights when it has focus). */
    FilePickerScreen ListView > ListItem.-highlight {
        background: $accent 60%;
        color: $text;
    }
    FilePickerScreen ListView:focus > ListItem.-highlight {
        background: $accent;
    }
    FilePickerScreen .actions {
        height: 3;
        margin-top: 1;
    }
    FilePickerScreen Button {
        margin-right: 1;
    }
    FilePickerScreen #picker-status {
        height: auto;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("up", "nav_up", show=False, priority=True),
        Binding("down", "nav_down", show=False, priority=True),
    ]

    def __init__(
        self,
        mode: Literal["save", "load"],
        title: str,
        default_path: str = "",
        kind: Kind = "any",
        must_exist: bool = False,
    ) -> None:
        super().__init__()
        self._mode = mode
        self._title = title
        self._default_path = default_path
        self._kind: Kind = kind
        self._suffix = _EXT_FOR_KIND[kind]
        self._must_exist = must_exist
        self._directory = self._resolve_directory(default_path)
        self._all_files: list[Path] = self._scan_files()
        # filtered list, in display order, kept in sync with the ListView
        self._displayed: list[Path] = []

    # ── compose ──────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Vertical(id="container"):
            yield Label(
                f"[b]{self._title}[/b]  [dim]({self._directory})  "
                f"filter: *{self._suffix}[/]"
            )
            yield Input(
                placeholder=(
                    "Type to filter…"
                    if self._mode == "load"
                    else f"Filename (without {self._suffix})…"
                ),
                id="picker-input",
            )
            yield ListView(id="picker-list")
            with Horizontal(classes="actions"):
                yield Button("OK", id="picker-ok", variant="primary")
                yield Button("Cancel", id="picker-cancel")
            yield Label("", id="picker-status")

    async def on_mount(self) -> None:
        await self._refilter("")
        self.query_one("#picker-input", Input).focus()

    # ── directory + scan ─────────────────────────────────────────────────────

    def _resolve_directory(self, default_path: str) -> Path:
        seed = Path(default_path).expanduser() if default_path else Path.cwd()
        if seed.is_file():
            return seed.parent
        if seed.is_dir():
            return seed
        if seed.parent.is_dir():
            return seed.parent
        return Path.cwd()

    def _scan_files(self) -> list[Path]:
        try:
            files = [
                p
                for p in self._directory.iterdir()
                if p.is_file() and p.name.endswith(self._suffix)
            ]
        except OSError:
            return []
        files.sort(key=lambda p: p.name.lower())
        return files

    # ── filter + display ─────────────────────────────────────────────────────

    async def _refilter(self, query: str) -> None:
        positions_by_file: dict[str, list[int]] = {}
        if not query:
            self._displayed = list(self._all_files)
        else:
            scored: list[tuple[int, Path, list[int]]] = []
            for p in self._all_files:
                m = fuzzy_match(query, p.name)
                if m is not None:
                    score, positions = m
                    scored.append((score, p, positions))
                    positions_by_file[p.name] = positions
            scored.sort(key=lambda t: (-t[0], t[1].name.lower()))
            self._displayed = [p for _, p, _pos in scored]
        lv = self.query_one("#picker-list", ListView)
        # Tear down old items and wait for them to actually unmount; then
        # mount the new ones and wait again. Only after both phases are
        # complete is it safe to set `index` — otherwise the highlight is
        # applied to widgets that are about to disappear (or that haven't
        # appeared yet) and silently vanishes.
        await lv.clear()
        if self._displayed:
            items = [
                ListItem(
                    Static(
                        _highlight_matches(
                            p.name, positions_by_file.get(p.name, [])
                        ),
                        markup=True,
                    )
                )
                for p in self._displayed
            ]
            await lv.extend(items)
            lv.index = 0

    # ── events ──────────────────────────────────────────────────────────────

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "picker-input":
            return
        if self._mode == "load":
            await self._refilter(event.value)
        else:
            # In save mode, the typed value is the proposed filename — no
            # filtering. We still show the directory's existing files for
            # reference, untouched.
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "picker-input":
            self._submit()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "picker-list":
            self._submit()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        # In save mode, clicking around the list pre-fills the filename input.
        if event.list_view.id != "picker-list":
            return
        if self._mode == "save" and event.list_view.index is not None:
            idx = event.list_view.index
            if 0 <= idx < len(self._displayed):
                name = self._displayed[idx].name
                # Strip the suffix so the input shows the base filename only.
                stem = name[: -len(self._suffix)] if name.endswith(self._suffix) else name
                self.query_one("#picker-input", Input).value = stem

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "picker-ok":
            self._submit()
        elif event.button.id == "picker-cancel":
            self.dismiss(None)

    # ── arrow key nav (priority so it works while Input is focused) ──────────

    def action_nav_up(self) -> None:
        lv = self.query_one("#picker-list", ListView)
        if lv.index is None or len(lv.children) == 0:
            return
        lv.index = max(0, lv.index - 1)

    def action_nav_down(self) -> None:
        lv = self.query_one("#picker-list", ListView)
        if len(lv.children) == 0:
            return
        if lv.index is None:
            lv.index = 0
        else:
            lv.index = min(len(lv.children) - 1, lv.index + 1)

    def action_cancel(self) -> None:
        self.dismiss(None)

    # ── submit ──────────────────────────────────────────────────────────────

    def _set_status(self, text: str) -> None:
        self.query_one("#picker-status", Label).update(text)

    def _submit(self) -> None:
        raw = self.query_one("#picker-input", Input).value.strip()
        if self._mode == "load":
            # Use highlighted list item if any; else try to parse raw as a path.
            lv = self.query_one("#picker-list", ListView)
            if lv.index is not None and 0 <= lv.index < len(self._displayed):
                self.dismiss(self._displayed[lv.index])
                return
            # Fallback: literal path
            if not raw:
                self._set_status("[red]No matching file. Type to search or press Esc.[/]")
                return
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = self._directory / path
            if self._must_exist and not path.is_file():
                self._set_status(f"[red]Not found: {path}[/red]")
                return
            self.dismiss(path)
            return
        # save mode
        if not raw:
            self._set_status("[red]Filename is required.[/red]")
            return
        # If the user typed an absolute or directory-relative path, accept it
        # as-is. Otherwise append the kind suffix and place in the directory.
        candidate = Path(raw).expanduser()
        if candidate.is_absolute() or "/" in raw or "\\" in raw:
            target = candidate
        else:
            name = raw
            if not name.endswith(self._suffix):
                name = f"{name}{self._suffix}"
            target = self._directory / name
        if not target.parent.exists():
            self._set_status(f"[red]Parent directory missing: {target.parent}[/red]")
            return
        self.dismiss(target)
