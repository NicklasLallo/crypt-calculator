from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Input, Label, Static

from ..optimize import DEFAULT_WEIGHTS, Objective, ObjectiveKind
from .widgets import colored_bucket

# When the search space grows past this, the optimizer can take long
# enough that a hint is worth showing.
BIG_SEARCH_SPACE = 20_000


class RunRequested(Message):
    def __init__(self, size_min: int, size_max: int, objective: Objective) -> None:
        super().__init__()
        self.size_min = size_min
        self.size_max = size_max
        self.objective = objective


class RunPane(VerticalScroll):
    BINDINGS = [
        Binding("ctrl+1", "run_max_perfect", "Run Perfect", priority=True),
        Binding("ctrl+2", "run_max_pg", "Run Perfect+Good", priority=True),
        Binding(
            "ctrl+3", "run_max_pga", "Run Perfect+Good+Accept", priority=True
        ),
        Binding("ctrl+4", "run_weighted", "Run weighted", priority=True),
    ]

    DEFAULT_CSS = """
    RunPane {
        padding: 1 2;
    }
    RunPane .row {
        height: 3;
        margin-bottom: 1;
    }
    RunPane Input.size-input {
        width: 10;
        margin-right: 2;
    }
    RunPane #union-buttons {
        height: 3;
        margin-bottom: 1;
    }
    RunPane #union-buttons Button {
        width: 1fr;
        margin-right: 1;
    }
    RunPane #weighted-box {
        height: auto;
        border: round $accent;
        padding: 1;
        margin: 0 0 1 0;
    }
    RunPane .weight-row {
        height: 3;
    }
    RunPane Input.weight-input {
        width: 8;
        margin: 0 1;
        padding: 0 1;
    }
    RunPane #weighted-box Button {
        width: 1fr;
        margin-top: 1;
    }
    RunPane #run-status {
        margin: 1 0;
        min-height: 1;
    }
    RunPane #info-panel {
        height: auto;
        border: round $accent;
        padding: 1 2;
        margin-top: 1;
    }
    RunPane #info-panel Static {
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("[b]Run optimization[/b]")
        with Horizontal(classes="row"):
            yield Label("Deck size: from ")
            yield Input(value="12", id="size-min", classes="size-input")
            yield Label(" to ")
            yield Input(value="14", id="size-max", classes="size-input")
        p = colored_bucket("perfect", bold=True)
        g = colored_bucket("good", bold=True)
        a = colored_bucket("acceptable", bold=True)
        u = colored_bucket("unacceptable", bold=True)
        with Horizontal(id="union-buttons"):
            yield Button(
                f"Maximize {p}", id="run-p", variant="primary"
            )
            yield Button(
                f"Maximize {p} + {g}", id="run-pg", variant="primary"
            )
            yield Button(
                f"Maximize {p} + {g} + {a}",
                id="run-pga",
                variant="primary",
            )
        with Vertical(id="weighted-box"):
            yield Label(
                f"[b]Weighted sum[/b] — score = w{p}·P(Perfect) + "
                f"w{g}·P(Good) + w{a}·P(Acceptable) + w{u}·P(Unacceptable). "
                "Integer weights; negatives allowed."
            )
            with Horizontal(classes="weight-row"):
                yield Label(p)
                yield Input(
                    value=str(int(DEFAULT_WEIGHTS[0])),
                    id="w-perfect",
                    classes="weight-input",
                )
                yield Label(g)
                yield Input(
                    value=str(int(DEFAULT_WEIGHTS[1])),
                    id="w-good",
                    classes="weight-input",
                )
                yield Label(a)
                yield Input(
                    value=str(int(DEFAULT_WEIGHTS[2])),
                    id="w-acceptable",
                    classes="weight-input",
                )
                yield Label(u)
                yield Input(
                    value=str(int(DEFAULT_WEIGHTS[3])),
                    id="w-unacceptable",
                    classes="weight-input",
                )
            yield Button(
                "Maximize weighted sum",
                id="run-weighted",
                variant="primary",
            )
        yield Static("", id="run-status")
        with Vertical(id="info-panel"):
            yield Static("[b]Search configuration[/b]", id="info-header")
            yield Static("(load a crypt and add rules to see info)", id="info-config")
            yield Static("", id="info-space")
            yield Static("", id="info-last-run")

    def status(self, text: str) -> None:
        self.query_one("#run-status", Static).update(text)

    def _read_size_range(self) -> tuple[int, int] | None:
        try:
            sz_min = int(self.query_one("#size-min", Input).value)
            sz_max = int(self.query_one("#size-max", Input).value)
        except ValueError:
            self.status("[red]Deck sizes must be integers[/red]")
            return None
        if sz_min < 4 or sz_max < sz_min:
            self.status("[red]Invalid size range (need min ≥ 4 and max ≥ min)[/red]")
            return None
        return sz_min, sz_max

    def read_weights(self) -> tuple[float, float, float, float] | None:
        """Read the four weight inputs. Returns None on parse error."""
        try:
            wp = int(self.query_one("#w-perfect", Input).value)
            wg = int(self.query_one("#w-good", Input).value)
            wa = int(self.query_one("#w-acceptable", Input).value)
            wu = int(self.query_one("#w-unacceptable", Input).value)
        except ValueError:
            self.status("[red]Weights must be integers[/red]")
            return None
        return (float(wp), float(wg), float(wa), float(wu))

    def _build_objective(self, kind: ObjectiveKind) -> Objective | None:
        if kind == "weighted":
            weights = self.read_weights()
            if weights is None:
                return None
            return Objective(kind="weighted", weights=weights)
        return Objective(kind=kind)

    def _trigger_run(self, kind: ObjectiveKind) -> None:
        sizes = self._read_size_range()
        if sizes is None:
            return
        objective = self._build_objective(kind)
        if objective is None:
            return
        self.post_message(RunRequested(sizes[0], sizes[1], objective))

    _BUTTON_TO_KIND: dict[str, ObjectiveKind] = {
        "run-p": "max_perfect",
        "run-pg": "max_pg",
        "run-pga": "max_pga",
        "run-weighted": "weighted",
    }

    def on_button_pressed(self, event: Button.Pressed) -> None:
        kind = self._BUTTON_TO_KIND.get(event.button.id or "")
        if kind is not None:
            self._trigger_run(kind)

    # Keybinding actions
    def action_run_max_perfect(self) -> None:
        self._trigger_run("max_perfect")

    def action_run_max_pg(self) -> None:
        self._trigger_run("max_pg")

    def action_run_max_pga(self) -> None:
        self._trigger_run("max_pga")

    def action_run_weighted(self) -> None:
        self._trigger_run("weighted")

    def show_info(
        self,
        *,
        crypt_size: int,
        referenced: list[str],
        anon_max_parts: int,
        size_min: int,
        size_max: int,
        breakdown: dict[int, int],
        total_decks: int,
        manual_total: int,
    ) -> None:
        cfg = [
            f"Crypt: [b]{crypt_size}[/b] named card{'s' if crypt_size != 1 else ''}",
            "Cards referenced by rules: "
            + (f"[b]{', '.join(referenced)}[/b]" if referenced else "[dim](none)[/dim]"),
            f"Free anon slots (unreferenced): [b]{anon_max_parts}[/b]",
            f"Deck size range: [b]{size_min}[/b] to [b]{size_max}[/b]",
            (
                f"Manual deck: [b]{manual_total}[/b] cards (will be evaluated alongside)"
                if manual_total > 0
                else "Manual deck: [dim](enter counts in the Crypt tab to compare)[/dim]"
            ),
        ]
        self.query_one("#info-config", Static).update("\n".join(cfg))

        space_lines = [
            f"[b]Search space[/b] — {total_decks:,} distinct "
            f"deck{'s' if total_decks != 1 else ''} to evaluate"
        ]
        for sz in sorted(breakdown):
            space_lines.append(f"  size {sz}: {breakdown[sz]:,} decks")
        if total_decks > BIG_SEARCH_SPACE:
            space_lines.append(
                "  [#D7A968]⚠ Big search space — this might take a "
                "little longer.[/]"
            )
        self.query_one("#info-space", Static).update("\n".join(space_lines))

    def show_run_summary(
        self,
        *,
        evaluated: int,
        elapsed_ms: float,
        top_p: float,
        top_pg: float,
        top_pga: float,
        top_weighted: float,
        weights: tuple[float, float, float, float],
    ) -> None:
        rate = evaluated / (elapsed_ms / 1000) if elapsed_ms > 0 else 0
        wp, wg, wa, wu = (int(w) for w in weights)
        p = colored_bucket("perfect")
        g = colored_bucket("good")
        a = colored_bucket("acceptable")
        u = colored_bucket("unacceptable")
        text = (
            "[b]Last run[/b]\n"
            f"  Elapsed: [b]{elapsed_ms:.1f} ms[/b]   "
            f"Throughput: [b]{rate:,.0f}[/b] decks/sec\n"
            f"  Decks evaluated: [b]{evaluated:,}[/b]\n"
            f"  Top P({p}):                                [b]{top_p:.4f}[/b]\n"
            f"  Top P({p} + {g}):                         [b]{top_pg:.4f}[/b]\n"
            f"  Top P({p} + {g} + {a}):            [b]{top_pga:.4f}[/b]\n"
            f"  Top weighted (w{p}={wp} w{g}={wg} w{a}={wa} w{u}={wu}): "
            f"[b]{top_weighted:.4f}[/b]"
        )
        self.query_one("#info-last-run", Static).update(text)
