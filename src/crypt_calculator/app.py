from __future__ import annotations

import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent, TabPane

from .deck import Deck
from .optimize import (
    DEFAULT_WEIGHTS,
    DeckResult,
    Objective,
    _score,
    optimize,
    search_space_breakdown,
)
from .pool import Pool
from .probability import HAND_SIZE, _bucket_breakdown
from .rules import RuleSet
from .screens.pool import PoolChanged, PoolLoaded, PoolPane, PoolReset
from .screens.results import ResultsPane
from .screens.rules import RulesChanged, RulesPane
from .screens.run import RunPane, RunRequested
from .screens.widgets import ConfirmScreen
from .userdata import (
    data_dir,
    install_examples,
    is_first_run,
    mark_first_run_done,
)


def _build_manual_deck(
    pool: Pool, ruleset: RuleSet, counts: dict[str, int]
) -> Deck | None:
    if sum(counts.values()) < HAND_SIZE:
        return None
    referenced_names = ruleset.referenced_cards()
    referenced = {name: counts.get(name, 0) for name in referenced_names}
    anon_counts: list[int] = []
    for name in pool.names:
        if name in referenced_names:
            continue
        c = counts.get(name, 0)
        if c > 0:
            anon_counts.append(c)
    anon = tuple(sorted(anon_counts, reverse=True))
    return Deck(referenced=referenced, anon=anon)


class CryptCalculatorApp(App):
    TITLE = "Crypt Calculator"
    SUB_TITLE = "Deck odds optimizer"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+e", "next_tab", "Next Tab", priority=True),
        Binding("ctrl+w", "prev_tab", "Prev Tab", priority=True),
    ]

    TABS_ORDER = ("tab-pool", "tab-rules", "tab-run", "tab-results")

    CSS = """
    Screen {
        background: $surface;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._pool = Pool(names=[])
        self._ruleset = RuleSet()

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="main-tabs"):
            with TabPane("Crypt", id="tab-pool"):
                yield PoolPane(self._pool, id="pool-pane")
            with TabPane("Rules", id="tab-rules"):
                yield RulesPane(self._pool, self._ruleset, id="rules-pane")
            with TabPane("Run", id="tab-run"):
                yield RunPane(id="run-pane")
            with TabPane("Results", id="tab-results"):
                yield ResultsPane(id="results-pane")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_run_info()
        if is_first_run():
            self._show_welcome()

    def _show_welcome(self) -> None:
        dest = data_dir()
        msg = (
            "Hello! It looks like this is your first run.\n\n"
            "Would you like to install the bundled example crypts and "
            f"rule-sets to [b]{dest}[/b]? Load them later from the "
            "Crypt / Rules tabs to see how the app works.\n\n"
            "You can always reinstall them via the [b]Install examples[/b] "
            "button on the Crypt tab."
        )

        def on_close(answer: bool | None) -> None:
            mark_first_run_done()
            if not answer:
                return
            try:
                copied = install_examples()
            except OSError:
                return
            try:
                pool_pane = self.query_one("#pool-pane", PoolPane)
            except Exception:
                return
            if copied:
                pool_pane._status(
                    f"Installed {len(copied)} example file(s) to {dest}"
                )
            else:
                pool_pane._status(f"Examples already present in {dest}")

        self.push_screen(
            ConfirmScreen(msg, title="Welcome to Crypt Calculator"),
            on_close,
        )

    def on_pool_changed(self, event: PoolChanged) -> None:
        self._pool = event.pool
        self.query_one("#rules-pane", RulesPane).set_pool(self._pool)
        self._refresh_run_info()

    def on_pool_loaded(self, event: PoolLoaded) -> None:
        """When a crypt is loaded from disk, check whether the current rules
        still reference cards that exist in it. If not, offer to clear them."""
        missing = self._ruleset.referenced_cards() - set(event.pool.names)
        if not missing:
            return
        cards = ", ".join(sorted(missing))
        msg = (
            "The current rules reference cards that are not in the loaded "
            f"crypt: [b]{cards}[/b].\n\n"
            "Clear all rules now? (Otherwise the optimizer will refuse to run "
            "until you fix the rules manually.)"
        )

        def on_close(result: bool | None) -> None:
            if not result:
                return
            self._ruleset.perfect.clear()
            self._ruleset.good.clear()
            self._ruleset.acceptable.clear()
            self.query_one("#rules-pane", RulesPane).set_ruleset(self._ruleset)
            self._refresh_run_info()

        self.push_screen(
            ConfirmScreen(msg, title="Crypt / rules mismatch"),
            on_close,
        )

    def on_pool_reset(self, event: PoolReset) -> None:
        self._ruleset = RuleSet()
        self.query_one("#rules-pane", RulesPane).set_ruleset(self._ruleset)
        self._refresh_run_info()

    def on_rules_changed(self, event: RulesChanged) -> None:
        self._ruleset = event.ruleset
        self._refresh_run_info()

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        # Refresh the Run info pane any time it becomes visible.
        if event.pane is not None and event.pane.id == "tab-run":
            self._refresh_run_info()
        # Move focus into the active pane so its BINDINGS reach the footer
        # (otherwise focus stays on the tab strip and per-pane keybindings —
        # e.g. "Load Crypt" / "Load Rules" on Ctrl+O — don't appear).
        if event.pane is not None:
            for child in event.pane.children:
                if child.can_focus:
                    child.focus()
                    break

    def _switch_tab(self, delta: int) -> None:
        tabs = self.query_one("#main-tabs", TabbedContent)
        try:
            idx = self.TABS_ORDER.index(tabs.active)
        except ValueError:
            return
        tabs.active = self.TABS_ORDER[(idx + delta) % len(self.TABS_ORDER)]

    def action_next_tab(self) -> None:
        self._switch_tab(+1)

    def action_prev_tab(self) -> None:
        self._switch_tab(-1)

    def _refresh_run_info(self) -> None:
        try:
            run = self.query_one("#run-pane", RunPane)
        except Exception:
            return
        try:
            pool = self.query_one("#pool-pane", PoolPane).collect()
            manual_counts = self.query_one("#pool-pane", PoolPane).collect_counts()
        except (ValueError, Exception):
            pool = self._pool
            manual_counts = {}
        referenced = sorted(self._ruleset.referenced_cards())
        # Read current size range from inputs
        try:
            sz_min = int(run.query_one("#size-min").value)
            sz_max = int(run.query_one("#size-max").value)
        except (ValueError, Exception):
            sz_min, sz_max = 12, 14
        if sz_max < sz_min:
            sz_max = sz_min
        if not pool.names:
            run.show_info(
                crypt_size=0,
                referenced=referenced,
                anon_max_parts=0,
                size_min=sz_min,
                size_max=sz_max,
                breakdown={},
                total_decks=0,
                manual_total=sum(manual_counts.values()),
            )
            return
        try:
            breakdown = search_space_breakdown(pool, self._ruleset, sz_min, sz_max)
        except Exception:
            breakdown = {}
        total = sum(breakdown.values())
        anon_max = max(0, pool.size() - len(referenced))
        run.show_info(
            crypt_size=pool.size(),
            referenced=referenced,
            anon_max_parts=anon_max,
            size_min=sz_min,
            size_max=sz_max,
            breakdown=breakdown,
            total_decks=total,
            manual_total=sum(manual_counts.values()),
        )

    async def on_run_requested(self, event: RunRequested) -> None:
        run = self.query_one("#run-pane", RunPane)
        try:
            self._pool = self.query_one("#pool-pane", PoolPane).collect()
        except ValueError as e:
            run.status(f"[red]Crypt invalid: {e}[/red]")
            return
        if not self._pool.names:
            run.status("[red]Crypt is empty — add card names first[/red]")
            return
        if self._ruleset.is_empty():
            run.status("[red]No rules defined — add at least one rule[/red]")
            return
        missing = self._ruleset.referenced_cards() - set(self._pool.names)
        if missing:
            run.status(
                f"[red]Rules reference cards not in crypt: {sorted(missing)}[/red]"
            )
            return
        manual_counts = self.query_one("#pool-pane", PoolPane).collect_counts()
        # Catch any leaked names not in the pool
        manual_counts = {n: c for n, c in manual_counts.items() if n in self._pool.names}

        run.status("[yellow]Running…[/yellow]")
        t0 = time.perf_counter()
        results, evaluated = optimize(
            self._pool,
            self._ruleset,
            size_min=event.size_min,
            size_max=event.size_max,
            objective=event.objective,
            top_k=3,
        )
        elapsed = (time.perf_counter() - t0) * 1000

        manual_result: DeckResult | None = None
        if manual_counts:
            manual_deck = _build_manual_deck(self._pool, self._ruleset, manual_counts)
            if manual_deck is not None and manual_deck.size >= HAND_SIZE:
                probs, outcomes = _bucket_breakdown(manual_deck, self._ruleset)
                manual_result = DeckResult(
                    deck=manual_deck,
                    probs=probs,
                    outcomes=outcomes,
                    score=_score(probs, event.objective),
                )

        # Compute top values for each objective across the top-K results, so
        # the info panel reads naturally regardless of which button was pressed.
        top_p = max((r.probs.get("perfect", 0.0) for r in results), default=0.0)
        top_pg = max(
            (r.probs.get("perfect", 0.0) + r.probs.get("good", 0.0) for r in results),
            default=0.0,
        )
        top_pga = max(
            (
                r.probs.get("perfect", 0.0)
                + r.probs.get("good", 0.0)
                + r.probs.get("acceptable", 0.0)
                for r in results
            ),
            default=0.0,
        )
        weights = event.objective.weights if event.objective.kind == "weighted" else DEFAULT_WEIGHTS
        top_weighted = max(
            (_score(r.probs, Objective(kind="weighted", weights=weights))[0] for r in results),
            default=0.0,
        )

        await self.query_one("#results-pane", ResultsPane).show_results(
            results,
            self._pool,
            elapsed,
            evaluated,
            manual_result=manual_result,
            manual_counts=manual_counts if manual_result is not None else None,
        )
        self.query_one("#main-tabs", TabbedContent).active = "tab-results"

        run.status(
            f"Computed top {len(results)} decks (evaluated {evaluated}) in {elapsed:.1f}ms"
            + (" • manual deck included" if manual_result is not None else "")
        )
        run.show_run_summary(
            evaluated=evaluated,
            elapsed_ms=elapsed,
            top_p=top_p,
            top_pg=top_pg,
            top_pga=top_pga,
            top_weighted=top_weighted,
            weights=weights,
        )
        self._refresh_run_info()


def main() -> None:
    CryptCalculatorApp().run()


if __name__ == "__main__":
    main()
