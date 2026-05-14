from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    ListItem,
    ListView,
    RadioSet,
    SelectionList,
    Static,
)
from textual.widgets.selection_list import Selection
from .widgets import DismissOnOutsideClickMixin, RadioButton, colored_bucket

from ..io import load_ruleset, save_ruleset
from ..pool import Pool
from ..rules import (
    Atom,
    Bucket,
    Clause,
    CountAtLeast,
    CountAtMost,
    CountEquals,
    RULE_BUCKETS,
    Rule,
    RuleSet,
    UniqueAtLeast,
)
from ..userdata import data_dir
from .filepicker import FilePickerScreen


# ──────────────────────────────────────────────────────────────────────────────
# Rule formatting helpers
# ──────────────────────────────────────────────────────────────────────────────


def format_atom(atom: Atom) -> str:
    if isinstance(atom, CountAtLeast):
        return f"≥{atom.k} {atom.card}"
    if isinstance(atom, CountAtMost):
        return f"≤{atom.k} {atom.card}"
    if isinstance(atom, CountEquals):
        return f"={atom.k} {atom.card}"
    if isinstance(atom, UniqueAtLeast):
        excl = ""
        if atom.excluding:
            excl = f" excluding {{{', '.join(sorted(atom.excluding))}}}"
        return f"≥{atom.k} unique{excl}"
    return repr(atom)


def format_clause(clause: Clause) -> str:
    parts = [format_atom(a) for a in clause]
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


def format_rule(rule: Rule) -> str:
    if not rule:
        return "(empty rule — always matches)"
    return " AND ".join(format_clause(c) for c in rule)


class RulesChanged(Message):
    def __init__(self, ruleset: RuleSet) -> None:
        super().__init__()
        self.ruleset = ruleset


# ──────────────────────────────────────────────────────────────────────────────
# RuleEditorScreen — unified Add / Edit modal
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class _AtomTypeOption:
    label: str
    value: str


_ATOM_TYPE_OPTIONS: list[_AtomTypeOption] = [
    _AtomTypeOption("≥ N copies of card", "count_at_least"),
    _AtomTypeOption("≤ N copies of card", "count_at_most"),
    _AtomTypeOption("= N copies of card", "count_equals"),
    _AtomTypeOption("≥ N unique cards", "unique_at_least"),
]

_TYPE_INDEX: dict[str, int] = {opt.value: i for i, opt in enumerate(_ATOM_TYPE_OPTIONS)}


def _atom_type_value(atom: Atom) -> str:
    if isinstance(atom, CountAtLeast):
        return "count_at_least"
    if isinstance(atom, CountAtMost):
        return "count_at_most"
    if isinstance(atom, CountEquals):
        return "count_equals"
    return "unique_at_least"


def _atom_card_names(atom: Atom) -> set[str]:
    """Cards an atom 'references' for the purpose of sibling-aware excluding."""
    if isinstance(atom, (CountAtLeast, CountAtMost, CountEquals)):
        return {atom.card}
    return set()


def _sibling_cards(clauses: list[list[Atom]], exclude_clause: int) -> set[str]:
    """Union of cards referenced by atoms in clauses OTHER than ``exclude_clause``.

    Used to seed a ``unique_at_least`` atom's excluding list from its siblings.
    """
    out: set[str] = set()
    for c, clause in enumerate(clauses):
        if c == exclude_clause:
            continue
        for atom in clause:
            out |= _atom_card_names(atom)
    return out


def _has_or_clause(clauses: list[list[Atom]]) -> bool:
    return any(len(c) > 1 for c in clauses)


def _or_pessimism_warning(clauses: list[list[Atom]], sel: tuple[int, int] | None) -> str:
    """If a ``unique_at_least`` atom is selected AND it pessimistically excludes
    cards that appear as OR alternatives elsewhere, return a hint string.
    Returns empty string when no warning applies.
    """
    if sel is None:
        return ""
    c, a = sel
    if c >= len(clauses) or a >= len(clauses[c]):
        return ""
    atom = clauses[c][a]
    if not isinstance(atom, UniqueAtLeast) or not atom.excluding:
        return ""
    # Collect cards that appear in any OR clause (size > 1) elsewhere.
    or_cards: set[str] = set()
    for other_c, other_clause in enumerate(clauses):
        if other_c == c or len(other_clause) <= 1:
            continue
        for other_atom in other_clause:
            or_cards |= _atom_card_names(other_atom)
    overlap = atom.excluding & or_cards
    if not overlap:
        return ""
    names = ", ".join(sorted(overlap))
    return (
        f"[yellow]Tip:[/] {names} appear in an OR clause but are pessimistically "
        "excluded here. Consider [b]Split on OR clauses[/] for a more accurate split."
    )


def expand_or_clauses(rule: list[list[Atom]]) -> list[list[list[Atom]]]:
    """Expand a CNF rule with OR-clauses into N flat (AND-only) rules.

    Each output rule is the cartesian product of picking one atom from each
    input clause. For every ``unique_at_least`` atom in the expanded rule, the
    excluding set is recomputed against the actually-claimed cards in that
    branch (instead of the pessimistic union across all OR alternatives).
    """
    from itertools import product

    if not rule:
        return []
    expanded: list[list[list[Atom]]] = []
    for combo in product(*rule):
        # combo: tuple of one atom per clause
        new_clauses: list[list[Atom]] = [[a] for a in combo]
        # Recompute excluding for unique_at_least atoms
        for i, atom in enumerate(combo):
            if isinstance(atom, UniqueAtLeast):
                siblings: set[str] = set()
                for j, other in enumerate(combo):
                    if j == i:
                        continue
                    siblings |= _atom_card_names(other)
                new_clauses[i] = [
                    UniqueAtLeast(k=atom.k, excluding=frozenset(siblings))
                ]
        expanded.append(new_clauses)
    return expanded


class RuleEditorScreen(
    DismissOnOutsideClickMixin,
    ModalScreen[tuple[list[Rule], Bucket] | None],
):
    """Modal that builds or edits a CNF rule and assigns it to a bucket.

    Open with ``rule=None`` to create a new rule from scratch; pass an existing
    rule to edit in place. Returns ``(list[rule], bucket)`` on Save (usually a
    single-element list, but the "Split on OR clauses" feature can return
    multiple). Returns ``None`` on Cancel (escape, click outside, Cancel).
    """

    DEFAULT_CSS = """
    RuleEditorScreen { align: center middle; }
    RuleEditorScreen #container {
        width: 120;
        height: 90%;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
    }
    RuleEditorScreen #bucket-row {
        height: 3;
        margin-bottom: 1;
    }
    RuleEditorScreen #bucket-row Label {
        width: 10;
        content-align: left middle;
    }
    RuleEditorScreen #bucket-select {
        layout: horizontal;
        height: 3;
    }
    RuleEditorScreen #preview {
        height: auto;
        min-height: 3;
        padding: 0 1;
        margin-bottom: 1;
        border: round $accent;
    }
    RuleEditorScreen #two-col {
        layout: horizontal;
        height: 1fr;
    }
    RuleEditorScreen #atom-list-pane {
        width: 55;
        padding: 0 1 0 0;
    }
    RuleEditorScreen #atom-list {
        height: auto;
    }
    RuleEditorScreen #atom-editor-pane {
        width: 1fr;
        padding: 0 0 0 1;
    }
    RuleEditorScreen .clause-header {
        margin-top: 1;
        color: $text-muted;
    }
    RuleEditorScreen .atom-row {
        height: 3;
    }
    RuleEditorScreen Button.atom-btn {
        width: 1fr;
        margin-right: 1;
    }
    RuleEditorScreen Button.atom-btn.selected-atom {
        background: $accent 60%;
        color: $text;
    }
    RuleEditorScreen Button.atom-del {
        min-width: 5;
        width: 5;
    }
    RuleEditorScreen Button.add-btn {
        margin: 1 0;
        width: 100%;
    }
    RuleEditorScreen RadioSet {
        height: auto;
        margin-bottom: 1;
    }
    RuleEditorScreen #excl-select {
        height: auto;
        max-height: 10;
        margin-bottom: 1;
    }
    RuleEditorScreen .form-row {
        height: 3;
        margin-bottom: 1;
    }
    RuleEditorScreen Input {
        margin-right: 1;
    }
    RuleEditorScreen #editor-hint {
        color: $text-muted;
        margin-top: 1;
    }
    RuleEditorScreen Button#sync-siblings {
        width: 100%;
        margin-bottom: 1;
    }
    RuleEditorScreen #or-hint {
        height: auto;
        margin-bottom: 1;
        padding: 0 1;
    }
    RuleEditorScreen #actions {
        height: 3;
        margin-top: 1;
    }
    RuleEditorScreen #actions Button {
        margin-right: 1;
    }
    RuleEditorScreen Button#expand-or {
        background: $warning 50%;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        Binding("enter", "save", "Save", priority=True, show=False),
    ]

    def __init__(
        self,
        pool: Pool,
        *,
        rule: Rule | None = None,
        bucket: Bucket = "perfect",
        title: str = "Rule editor",
    ) -> None:
        super().__init__()
        self.pool = pool
        self._title = title
        # Deep-copy clauses so edits inside the modal don't leak out on Cancel.
        self.clauses: list[list[Atom]] = [list(c) for c in (rule or [])]
        self.initial_bucket: Bucket = bucket
        self.selected: tuple[int, int] | None = None
        # Set during _populate_editor_from_selection so racing Changed events
        # don't overwrite the just-selected atom. Cleared via call_after_refresh
        # so it survives until the queued events have drained.
        self._populating = False

    # ── compose ──────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Vertical(id="container"):
            yield Label(f"[b]{self._title}[/b]")
            with Horizontal(id="bucket-row"):
                yield Label("Bucket:")
                with RadioSet(id="bucket-select"):
                    yield RadioButton(
                        colored_bucket("perfect"),
                        value=(self.initial_bucket == "perfect"),
                        id="b-perfect",
                    )
                    yield RadioButton(
                        colored_bucket("good"),
                        value=(self.initial_bucket == "good"),
                        id="b-good",
                    )
                    yield RadioButton(
                        colored_bucket("acceptable"),
                        value=(self.initial_bucket == "acceptable"),
                        id="b-acceptable",
                    )
            yield Label("[b]Preview:[/b]")
            yield Static("", id="preview")
            with Horizontal(id="two-col"):
                with VerticalScroll(id="atom-list-pane"):
                    yield Vertical(id="atom-list")
                with VerticalScroll(id="atom-editor-pane"):
                    yield Label("[b]Atom type:[/b]", id="type-label")
                    with RadioSet(id="type-select"):
                        for i, opt in enumerate(_ATOM_TYPE_OPTIONS):
                            yield RadioButton(opt.label, id=f"t-{i}")
                    yield Label("[b]Card[/b] (for count rules):", id="card-label")
                    with RadioSet(id="card-select"):
                        for i, name in enumerate(self.pool.names):
                            yield RadioButton(name, id=f"card-{i}")
                    with Horizontal(classes="form-row", id="n-row"):
                        yield Label("N: ")
                        yield Input(placeholder="N (integer ≥ 0)", id="n-input", value="1")
                    yield Label(
                        "[b]Excluding[/b] (for unique-at-least):", id="excl-label"
                    )
                    yield SelectionList[int](
                        *[Selection(name, i) for i, name in enumerate(self.pool.names)],
                        id="excl-select",
                    )
                    yield Button(
                        "Sync excluded with sibling atoms",
                        id="sync-siblings",
                        tooltip="Tick every card referenced by atoms in OTHER "
                        "clauses of this rule — the typical 'one more card "
                        "besides the ones already required' pattern.",
                    )
                    yield Static("", id="or-hint")
                    yield Static("", id="editor-hint")
            with Horizontal(id="actions"):
                yield Button("Save rule", id="save", variant="primary")
                yield Button("Cancel", id="cancel")
                yield Button(
                    "Split on OR clauses",
                    id="expand-or",
                    tooltip="Replace this rule with one rule per OR-clause "
                    "combination, recomputing excluding sets per branch.",
                )

    # ── mount-time setup ─────────────────────────────────────────────────────

    async def on_mount(self) -> None:
        await self._render_atom_list()
        self._refresh_preview()
        # If editing a non-empty rule, select the first atom.
        first = self._first_atom_index()
        self._set_selected(first)

    # ── small accessors ──────────────────────────────────────────────────────

    def _first_atom_index(self) -> tuple[int, int] | None:
        for c, clause in enumerate(self.clauses):
            if clause:
                return (c, 0)
        return None

    def _selected_bucket(self) -> Bucket:
        for name in ("perfect", "good", "acceptable"):
            rb = self.query_one(f"#b-{name}", RadioButton)
            if rb.value:
                return cast(Bucket, name)
        return self.initial_bucket

    def _selected_atom(self) -> Atom | None:
        if self.selected is None:
            return None
        c, a = self.selected
        if c < 0 or c >= len(self.clauses):
            return None
        clause = self.clauses[c]
        if a < 0 or a >= len(clause):
            return None
        return clause[a]

    def _default_atom(self) -> Atom:
        if self.pool.names:
            return CountAtLeast(card=self.pool.names[0], k=1)
        return UniqueAtLeast(k=1)

    # ── atom-list rendering ──────────────────────────────────────────────────

    async def _render_atom_list(self) -> None:
        container = self.query_one("#atom-list", Vertical)
        await container.remove_children()
        widgets: list = []
        if not self.clauses:
            widgets.append(
                Static(
                    "[dim italic](no atoms yet — click '+ New clause' below)[/]",
                    classes="atom-empty",
                )
            )
        for c, clause in enumerate(self.clauses):
            widgets.append(Label(f"[b]Clause {c + 1}[/b]", classes="clause-header"))
            for a, atom in enumerate(clause):
                widgets.append(
                    Horizontal(
                        Button(format_atom(atom), id=f"atom-{c}-{a}", classes="atom-btn"),
                        Button("✕", id=f"del-{c}-{a}", classes="atom-del"),
                        classes="atom-row",
                    )
                )
            widgets.append(
                Button("+ Add OR atom", id=f"add-or-{c}", classes="add-btn")
            )
        widgets.append(
            Button("+ New clause (AND)", id="add-and", classes="add-btn")
        )
        await container.mount_all(widgets)
        self._highlight_selected()

    def _highlight_selected(self) -> None:
        for btn in self.query(".atom-btn"):
            btn.remove_class("selected-atom")
        if self.selected is None:
            return
        c, a = self.selected
        try:
            btn = self.query_one(f"#atom-{c}-{a}", Button)
            btn.add_class("selected-atom")
        except Exception:
            pass

    def _refresh_preview(self) -> None:
        text = format_rule(self.clauses) if any(self.clauses) else format_rule([])
        self.query_one("#preview", Static).update(text)

    def _refresh_atom_button_label(self, c: int, a: int) -> None:
        try:
            btn = self.query_one(f"#atom-{c}-{a}", Button)
            btn.label = format_atom(self.clauses[c][a])
        except Exception:
            pass

    def _refresh_or_hint(self) -> None:
        """Update the OR-pessimism hint Static for the currently-selected atom."""
        try:
            hint = self.query_one("#or-hint", Static)
        except Exception:
            return
        hint.update(_or_pessimism_warning(self.clauses, self.selected))
        # Also refresh Split-on-OR button enabled state.
        try:
            self.query_one("#expand-or", Button).disabled = not _has_or_clause(self.clauses)
        except Exception:
            pass

    def _sync_siblings_into_excluding(self) -> None:
        """Tick all sibling-referenced cards in the Excluding list, then re-apply."""
        if self.selected is None:
            return
        c, _ = self.selected
        cards = _sibling_cards(self.clauses, c)
        sl = self.query_one("#excl-select", SelectionList)
        sl.deselect_all()
        for name in cards:
            if name in self.pool.names:
                sl.select(self.pool.names.index(name))
        # The user-initiated tick fires SelectedChanged → _apply rebuilds the
        # atom from the updated selection. No further work needed here.

    # ── selection management ─────────────────────────────────────────────────

    def _set_selected(self, sel: tuple[int, int] | None) -> None:
        self.selected = sel
        self._highlight_selected()
        self._populate_editor_from_selection()

    def _populate_editor_from_selection(self) -> None:
        atom = self._selected_atom()
        # Hide / show editor based on whether an atom is selected.
        editor_visible = atom is not None
        for wid in ("type-label", "type-select", "card-label", "card-select", "n-row"):
            self.query_one(f"#{wid}").display = editor_visible
        if atom is None:
            self.query_one("#excl-label", Label).display = False
            self.query_one("#excl-select", SelectionList).display = False
            self.query_one("#sync-siblings", Button).display = False
            self.query_one("#editor-hint", Static).update(
                "[dim italic](Click an atom on the left to edit it, or use the "
                "Add buttons to create one.)[/]"
            )
            self._refresh_or_hint()
            return
        self.query_one("#editor-hint", Static).update("")

        # Mark "populating" so the cascade of Changed events fired by the value
        # sets below is recognized as our doing — handlers no-op while this is
        # True. We deliberately don't use ``self.prevent(Changed)`` because
        # that *also* swallows RadioSet's own internal mutex enforcement,
        # which would leave both the old and new buttons looking pressed.
        # The flag is cleared in a deferred callback so it stays True until
        # those queued Changed events have drained.
        self._populating = True
        try:
            # Atom-type radio. RadioSet *prevents* a button being explicitly
            # set to False (its handler immediately reverts) — so we only
            # ever set the target radio to True and let the RadioSet auto-
            # deselect the previously-pressed sibling.
            target_idx = _TYPE_INDEX[_atom_type_value(atom)]
            target_rb = self.query_one(f"#t-{target_idx}", RadioButton)
            if not target_rb.value:
                target_rb.value = True
            # Card radio (only meaningful for count_* atoms — for unique
            # atoms we don't touch the card RadioSet since it's hidden).
            if isinstance(atom, (CountAtLeast, CountAtMost, CountEquals)):
                if atom.card in self.pool.names:
                    idx = self.pool.names.index(atom.card)
                    target_card = self.query_one(f"#card-{idx}", RadioButton)
                    if not target_card.value:
                        target_card.value = True
            # N
            self.query_one("#n-input", Input).value = str(atom.k)
            # Excluding (SelectionList, no "must have one" invariant)
            sl = self.query_one("#excl-select", SelectionList)
            sl.deselect_all()
            if isinstance(atom, UniqueAtLeast):
                for name in atom.excluding:
                    if name in self.pool.names:
                        sl.select(self.pool.names.index(name))
        finally:
            # Let the queued Changed events fire first; clear the flag after.
            self.call_after_refresh(self._end_populating)
        # Show/hide card vs. excluding based on type, and refresh the
        # OR-pessimism hint for the now-selected atom.
        self._refresh_type_visibility()
        self._refresh_or_hint()

    def _end_populating(self) -> None:
        self._populating = False

    def _refresh_type_visibility(self) -> None:
        atom = self._selected_atom()
        if atom is None:
            for wid in ("sync-siblings",):
                self.query_one(f"#{wid}").display = False
            return
        is_unique = isinstance(atom, UniqueAtLeast)
        self.query_one("#card-label", Label).display = not is_unique
        self.query_one("#card-select", RadioSet).display = not is_unique
        self.query_one("#excl-label", Label).display = is_unique
        self.query_one("#excl-select", SelectionList).display = is_unique
        self.query_one("#sync-siblings", Button).display = is_unique

    # ── atom mutations ───────────────────────────────────────────────────────

    def _read_atom_from_editor(self) -> Atom | None:
        """Build an Atom from the form's current state. Returns None if invalid."""
        # Type
        rs = self.query_one("#type-select", RadioSet)
        pressed = rs.pressed_button
        if pressed is None or pressed.id is None:
            return None
        type_idx = int(pressed.id.removeprefix("t-"))
        atom_type = _ATOM_TYPE_OPTIONS[type_idx].value
        # N
        n_str = self.query_one("#n-input", Input).value.strip()
        if not n_str:
            return None
        try:
            k = int(n_str)
        except ValueError:
            return None
        if k < 0:
            return None
        # Card (for count_*)
        if atom_type in ("count_at_least", "count_at_most", "count_equals"):
            card_rs = self.query_one("#card-select", RadioSet)
            cp = card_rs.pressed_button
            if cp is None or cp.id is None:
                return None
            card_idx = int(cp.id.removeprefix("card-"))
            card_name = self.pool.names[card_idx]
            if atom_type == "count_at_least":
                return CountAtLeast(card=card_name, k=k)
            if atom_type == "count_at_most":
                return CountAtMost(card=card_name, k=k)
            return CountEquals(card=card_name, k=k)
        # Excluding (for unique_at_least)
        sl = self.query_one("#excl-select", SelectionList)
        excluding = frozenset(self.pool.names[i] for i in sl.selected)
        return UniqueAtLeast(k=k, excluding=excluding)

    def _apply_editor_to_selection(self) -> None:
        """Read form, replace selected atom, refresh UI. No-op if unchanged."""
        if self._populating or self.selected is None:
            return
        atom = self._read_atom_from_editor()
        if atom is None:
            return  # invalid state — leave atom unchanged, user keeps typing
        c, a = self.selected
        if self.clauses[c][a] == atom:
            return  # no real change
        self.clauses[c][a] = atom
        self._refresh_atom_button_label(c, a)
        self._refresh_preview()
        self._refresh_or_hint()

    async def _add_atom_to_clause(self, c: int) -> None:
        atom = self._default_atom()
        self.clauses[c].append(atom)
        new_idx = len(self.clauses[c]) - 1
        await self._render_atom_list()
        self._refresh_preview()
        self._set_selected((c, new_idx))

    async def _new_clause(self) -> None:
        atom = self._default_atom()
        self.clauses.append([atom])
        new_c = len(self.clauses) - 1
        await self._render_atom_list()
        self._refresh_preview()
        self._set_selected((new_c, 0))

    async def _delete_atom(self, c: int, a: int) -> None:
        if c >= len(self.clauses) or a >= len(self.clauses[c]):
            return
        self.clauses[c].pop(a)
        next_sel: tuple[int, int] | None = None
        if not self.clauses[c]:
            # Collapse empty clause
            self.clauses.pop(c)
            # Try last atom of previous clause, else first atom of next clause
            if c - 1 >= 0 and self.clauses[c - 1]:
                next_sel = (c - 1, len(self.clauses[c - 1]) - 1)
            elif c < len(self.clauses) and self.clauses[c]:
                next_sel = (c, 0)
        else:
            # Stay in clause; pick adjacent atom
            if a >= len(self.clauses[c]):
                a = len(self.clauses[c]) - 1
            next_sel = (c, a)
        await self._render_atom_list()
        self._refresh_preview()
        self._set_selected(next_sel)

    # ── events ──────────────────────────────────────────────────────────────

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "save":
            self._do_save()
        elif bid == "cancel":
            self.dismiss(None)
        elif bid == "expand-or":
            self._do_expand_or()
        elif bid == "sync-siblings":
            self._sync_siblings_into_excluding()
        elif bid == "add-and":
            await self._new_clause()
        elif bid.startswith("add-or-"):
            try:
                c = int(bid.removeprefix("add-or-"))
            except ValueError:
                return
            await self._add_atom_to_clause(c)
        elif bid.startswith("atom-"):
            parts = bid.removeprefix("atom-").split("-")
            if len(parts) == 2:
                self._set_selected((int(parts[0]), int(parts[1])))
        elif bid.startswith("del-"):
            parts = bid.removeprefix("del-").split("-")
            if len(parts) == 2:
                await self._delete_atom(int(parts[0]), int(parts[1]))

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if self._populating:
            return
        rs_id = event.radio_set.id or ""
        if rs_id == "bucket-select":
            return  # change is read on Save; no live update needed
        if rs_id == "type-select":
            # Read the form first, replace the atom, then re-evaluate which
            # field block to show (card vs excluding).
            self._apply_editor_to_selection()
            self._refresh_type_visibility()
            return
        if rs_id == "card-select":
            self._apply_editor_to_selection()
            return

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._populating:
            return
        if event.input.id == "n-input":
            self._apply_editor_to_selection()

    def on_input_focused(self, event: Input.Focused) -> None:
        # On focus, select all text in the N input so typing replaces the old
        # number instead of requiring the user to delete first.
        if event.input.id == "n-input":
            try:
                event.input.action_select_all()
            except Exception:
                pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter inside an Input doesn't bubble to the screen's Enter binding —
        # handle it explicitly so the user can save without leaving the field.
        if event.input.id == "n-input":
            self._do_save()

    def on_selection_list_selected_changed(
        self, event: SelectionList.SelectedChanged
    ) -> None:
        if self._populating:
            return
        if event.selection_list.id == "excl-select":
            self._apply_editor_to_selection()

    # ── save / cancel / expand / sync ────────────────────────────────────────

    def action_save(self) -> None:
        self._do_save()

    def _do_save(self) -> None:
        # Drop empty clauses defensively (should already be collapsed).
        self.clauses = [c for c in self.clauses if c]
        if not self.clauses:
            self.notify(
                "Add at least one atom before saving.", severity="error"
            )
            return
        self.dismiss(([list(self.clauses)], self._selected_bucket()))

    def _do_expand_or(self) -> None:
        # Drop empty clauses defensively.
        self.clauses = [c for c in self.clauses if c]
        if not self.clauses:
            self.notify("Add at least one atom first.", severity="error")
            return
        if not _has_or_clause(self.clauses):
            self.notify(
                "Nothing to split — this rule has no OR clauses.",
                severity="warning",
            )
            return
        expanded = expand_or_clauses(self.clauses)
        if not expanded:
            self.notify("OR-expansion produced no rules.", severity="error")
            return
        self.notify(
            f"Split into {len(expanded)} rule{'s' if len(expanded) != 1 else ''}.",
        )
        self.dismiss((expanded, self._selected_bucket()))

    def action_cancel(self) -> None:
        self.dismiss(None)


# ──────────────────────────────────────────────────────────────────────────────
# RulesPane — three bucket sections with Add / Edit / Delete actions
# ──────────────────────────────────────────────────────────────────────────────


class RulesPane(VerticalScroll):
    BINDINGS = [
        Binding("ctrl+o", "load", "Load Rules", priority=True),
        Binding("ctrl+s", "save", "Save Rules", priority=True),
        Binding("enter", "edit_selected", "Edit", priority=True),
        Binding("delete", "delete_selected", "Delete", priority=True),
    ]

    DEFAULT_CSS = """
    RulesPane {
        padding: 1 2;
    }
    RulesPane .bucket-section {
        height: auto;
        margin-bottom: 1;
        border: round $accent;
        padding: 1;
    }
    RulesPane ListView {
        height: auto;
        min-height: 3;
        max-height: 12;
    }
    RulesPane .bucket-actions {
        height: auto;
        margin-top: 1;
    }
    RulesPane Button {
        margin-right: 1;
    }
    RulesPane #ruleset-actions {
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, pool: Pool, ruleset: RuleSet, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pool = pool
        self._ruleset = ruleset
        self._last_path: Path | None = None
        # Which bucket's ListView most recently got user focus / interaction.
        self._active_bucket: Bucket = "perfect"

    def compose(self) -> ComposeResult:
        yield Label(
            "[b]Rules[/b] — priority: "
            f"{colored_bucket('perfect', bold=True)} > "
            f"{colored_bucket('good', bold=True)} > "
            f"{colored_bucket('acceptable', bold=True)} > "
            f"(default: {colored_bucket('unacceptable', bold=True)})"
        )
        for bucket in RULE_BUCKETS:
            with Container(classes="bucket-section", id=f"section-{bucket}"):
                yield Label(colored_bucket(bucket, bold=True))
                yield ListView(id=f"list-{bucket}")
                with Horizontal(classes="bucket-actions"):
                    yield Button(
                        f"Add new {colored_bucket(bucket)} rule",
                        id=f"add-{bucket}",
                    )
                    yield Button("Edit selected", id=f"edit-{bucket}")
                    yield Button("Delete selected", id=f"delete-{bucket}")
        with Horizontal(id="ruleset-actions"):
            yield Button("Load…", id="rules-load")
            yield Button("Save…", id="rules-save")
            yield Static("", id="rules-status")

    def on_mount(self) -> None:
        self._refresh_lists()

    def set_pool(self, pool: Pool) -> None:
        self._pool = pool

    def set_ruleset(self, rs: RuleSet) -> None:
        self._ruleset = rs
        self._refresh_lists()
        self.post_message(RulesChanged(self._ruleset))

    def ruleset(self) -> RuleSet:
        return self._ruleset

    def _refresh_lists(self) -> None:
        for bucket in RULE_BUCKETS:
            lv = self.query_one(f"#list-{bucket}", ListView)
            lv.clear()
            for r in getattr(self._ruleset, bucket):
                lv.append(ListItem(Static(format_rule(r))))

    def _status(self, text: str) -> None:
        self.query_one("#rules-status", Static).update(text)

    # ── tracking which bucket-list the user is currently in ──────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        lv_id = (event.list_view.id or "")
        if lv_id.startswith("list-"):
            bucket = cast(Bucket, lv_id.removeprefix("list-"))
            if bucket in RULE_BUCKETS:
                self._active_bucket = bucket

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        # Mouse-click / Enter on a ListItem: open editor on that rule.
        lv_id = (event.list_view.id or "")
        if not lv_id.startswith("list-"):
            return
        bucket = cast(Bucket, lv_id.removeprefix("list-"))
        if bucket not in RULE_BUCKETS:
            return
        self._active_bucket = bucket
        idx = event.list_view.index
        if idx is None:
            return
        self._open_edit_modal(bucket, idx)

    def _selected_index(self, bucket: Bucket) -> int | None:
        lv = self.query_one(f"#list-{bucket}", ListView)
        return lv.index

    # ── button / keybinding dispatch ─────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "rules-load":
            self._do_load()
            return
        if bid == "rules-save":
            self._do_save()
            return
        for bucket in RULE_BUCKETS:
            if bid == f"add-{bucket}":
                self._active_bucket = bucket
                self._open_add_modal(bucket)
                return
            if bid == f"edit-{bucket}":
                self._active_bucket = bucket
                idx = self._selected_index(bucket)
                if idx is None:
                    self._status(
                        f"[yellow]Select a {bucket} rule first (click it in the list).[/]"
                    )
                    return
                self._open_edit_modal(bucket, idx)
                return
            if bid == f"delete-{bucket}":
                self._active_bucket = bucket
                idx = self._selected_index(bucket)
                if idx is None:
                    self._status(
                        f"[yellow]Select a {bucket} rule first (click it in the list).[/]"
                    )
                    return
                self._delete_rule(bucket, idx)
                return

    def action_edit_selected(self) -> None:
        bucket = self._active_bucket
        idx = self._selected_index(bucket)
        if idx is None:
            self._status(
                f"[yellow]Highlight a {bucket} rule first (use ↑/↓ in its list).[/]"
            )
            return
        self._open_edit_modal(bucket, idx)

    def action_delete_selected(self) -> None:
        bucket = self._active_bucket
        idx = self._selected_index(bucket)
        if idx is None:
            self._status(
                f"[yellow]Highlight a {bucket} rule first (use ↑/↓ in its list).[/]"
            )
            return
        self._delete_rule(bucket, idx)

    # ── add / edit / delete operations ───────────────────────────────────────

    def _open_add_modal(self, bucket: Bucket) -> None:
        if not self._pool.names:
            self._status("[red]Define crypt names first[/red]")
            return

        def on_close(result: tuple[list[Rule], Bucket] | None) -> None:
            if result is None:
                return
            new_rules, new_bucket = result
            target = getattr(self._ruleset, new_bucket)
            for r in new_rules:
                target.append(r)
            self._refresh_lists()
            self.post_message(RulesChanged(self._ruleset))

        self.app.push_screen(
            RuleEditorScreen(self._pool, rule=None, bucket=bucket, title="New rule"),
            on_close,
        )

    def _open_edit_modal(self, bucket: Bucket, idx: int) -> None:
        if not self._pool.names:
            self._status("[red]Define crypt names first[/red]")
            return
        bucket_list: list[Rule] = getattr(self._ruleset, bucket)
        if idx < 0 or idx >= len(bucket_list):
            return
        old_rule = bucket_list[idx]

        def on_close(result: tuple[list[Rule], Bucket] | None) -> None:
            if result is None:
                return
            new_rules, new_bucket = result
            if not new_rules:
                # The editor wouldn't normally return empty, but be defensive.
                return
            if new_bucket == bucket:
                # Replace at idx with first rule (preserves position),
                # append any remaining (from Split-on-OR expansion).
                bucket_list[idx] = new_rules[0]
                for r in new_rules[1:]:
                    bucket_list.append(r)
            else:
                bucket_list.pop(idx)
                target = getattr(self._ruleset, new_bucket)
                for r in new_rules:
                    target.append(r)
                self._active_bucket = new_bucket
            self._refresh_lists()
            self.post_message(RulesChanged(self._ruleset))

        self.app.push_screen(
            RuleEditorScreen(
                self._pool, rule=old_rule, bucket=bucket, title="Edit rule"
            ),
            on_close,
        )

    def _delete_rule(self, bucket: Bucket, idx: int) -> None:
        bucket_list: list[Rule] = getattr(self._ruleset, bucket)
        if idx < 0 or idx >= len(bucket_list):
            return
        bucket_list.pop(idx)
        self._refresh_lists()
        self.post_message(RulesChanged(self._ruleset))

    # ── load / save ──────────────────────────────────────────────────────────

    def _default_path(self) -> str:
        if self._last_path is not None:
            return str(self._last_path)
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        return str(d / "untitled.rules.yaml")

    def action_load(self) -> None:
        self._do_load()

    def action_save(self) -> None:
        self._do_save()

    def _do_load(self) -> None:
        def on_close(result: Path | None) -> None:
            if result is None:
                return
            try:
                rs, note = load_ruleset(result, self._pool)
            except Exception as e:
                self._status(f"[red]Load failed: {e}[/red]")
                return
            self.set_ruleset(rs)
            self._last_path = result
            if note:
                self._status(f"Loaded {result} — [yellow]{note}[/yellow]")
            else:
                self._status(f"Loaded {result}")

        self.app.push_screen(
            FilePickerScreen(
                mode="load",
                title="Load rules",
                default_path=self._default_path(),
                kind="rules",
                must_exist=True,
            ),
            on_close,
        )

    def _do_save(self) -> None:
        def on_close(result: Path | None) -> None:
            if result is None:
                return
            try:
                save_ruleset(self._ruleset, result)
            except Exception as e:
                self._status(f"[red]Save failed: {e}[/red]")
                return
            self._last_path = result
            self._status(f"Saved to {result}")

        self.app.push_screen(
            FilePickerScreen(
                mode="save",
                title="Save rules",
                default_path=self._default_path(),
                kind="rules",
                must_exist=False,
            ),
            on_close,
        )
