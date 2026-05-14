from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static, TabbedContent, TabPane

from ..optimize import DeckResult
from ..pool import Pool
from ..rules import BUCKETS, Bucket
from .card_art import CardArtPanel
from .widgets import BUCKET_COLORS

BAR_WIDTH = 30

# Delta colors used in the comparison panel. Slightly more saturated than the
# bucket palette so improvements/regressions read at a glance, without going
# back to neon green/red.
DELTA_BETTER = "#5BAA5B"
DELTA_WORSE = "#B85B5B"
DELTA_ZERO = "#888888"


def _bar(p: float) -> str:
    filled = int(round(p * BAR_WIDTH))
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def _small_bar(p: float, width: int) -> str:
    filled = int(round(p * width))
    return "█" * filled + "░" * (width - filled)


def _stacked_bar(probs: dict[Bucket, float], width: int = BAR_WIDTH) -> str:
    """Single stacked horizontal bar coloured by bucket, totalling 100%.

    Unacceptable absorbs the remainder so rounding never overshoots.
    """
    p = probs.get("perfect", 0.0)
    g = probs.get("good", 0.0)
    a = probs.get("acceptable", 0.0)
    pn = int(round(p * width))
    gn = int(round(g * width))
    an = int(round(a * width))
    un = max(width - pn - gn - an, 0)
    return (
        f"[{BUCKET_COLORS['perfect']}]" + "█" * pn + "[/]"
        f"[{BUCKET_COLORS['good']}]" + "█" * gn + "[/]"
        f"[{BUCKET_COLORS['acceptable']}]" + "█" * an + "[/]"
        f"[{BUCKET_COLORS['unacceptable']}]" + "█" * un + "[/]"
    )


def _format_probs(probs: dict[Bucket, float]) -> str:
    lines = []
    for bucket in BUCKETS:
        color = BUCKET_COLORS[bucket]
        value = probs.get(bucket, 0.0)
        bar = _bar(value)
        lines.append(
            f"[{color}]{bucket.capitalize():<13}[/] "
            f"[{color}]{bar}[/] {value*100:5.1f}%"
        )
    lines.append("")
    lines.append("Stacked: " + _stacked_bar(probs))
    return "\n".join(lines)


def _format_optimizer_deck(result: DeckResult, pool: Pool) -> str:
    """Optimizer-output deck — anon slots auto-filled in pool order, shown subdued."""
    lines = [f"[b]Deck — {result.deck.size} cards[/b]"]
    if pool is not None and pool.names:
        for name, count, is_anon in result.deck.named_lines(pool):
            if is_anon:
                lines.append(f"  [#D7A968]{count} × {name}[/]")
            else:
                lines.append(f"  {count} × {name}")
        lines.append(
            "  [dim italic]Highlighted entries are auto-filled — any "
            "unreferenced crypt card works equally well in those slots.[/]"
        )
    else:
        for line in result.deck.describe(anon_label="other card"):
            lines.append(f"  {line}")
    return "\n".join(lines)


def _format_manual_deck(result: DeckResult, counts: dict[str, int], pool: Pool) -> str:
    """Manual deck — render the user's exact entries from the Crypt tab."""
    total = sum(counts.values())
    lines = [f"[b]Your deck — {total} cards[/b]"]
    for name in pool.names:
        c = counts.get(name, 0)
        if c > 0:
            lines.append(f"  {c} × {name}")
    return "\n".join(lines)


def _format_outcomes(result: DeckResult, limit: int = 8) -> str:
    lines = ["", f"[b]Top draw outcomes (top {limit}):[/b]"]
    for hand, bucket, p in result.outcomes[:limit]:
        ref_str = ", ".join(
            f"{count}×{name}" for name, count in hand.referenced.items() if count > 0
        ) or "—"
        anon_str = (
            "+".join(str(c) for c in hand.anon_draws) + " other(s)"
            if hand.anon_draws
            else ""
        )
        descr = ref_str + (" + " + anon_str if anon_str else "")
        color = BUCKET_COLORS[bucket]
        lines.append(f"  {p*100:5.1f}%  [{color}]{bucket[:4]}[/]  {descr}")
    return "\n".join(lines)


def _format_comparison(
    selected: DeckResult,
    selected_label: str,
    manual: DeckResult,
) -> str:
    """Side-by-side bars for the selected vs. manual deck, with per-bucket Δ."""
    sub_w = 20
    header = (
        f"[b]Comparison:[/b] Manual List vs {selected_label}   "
        f"[dim](Δ = selected − manual)[/]"
    )
    col_hdr = (
        f"  {'Bucket':<13} "
        f"  {'Manual':^{sub_w + 7}}    "
        f"  {'Selected':^{sub_w + 7}}    Δ"
    )
    lines = [header, "", col_hdr]
    for bucket in BUCKETS:
        color = BUCKET_COLORS[bucket]
        s = selected.probs.get(bucket, 0.0)
        m = manual.probs.get(bucket, 0.0)
        delta = s - m
        # Perfect/Good/Acceptable: higher is better. Unacceptable: lower is better.
        better_when_positive = bucket != "unacceptable"
        if abs(delta) < 1e-9:
            delta_color = DELTA_ZERO
        elif (delta > 0) == better_when_positive:
            delta_color = DELTA_BETTER
        else:
            delta_color = DELTA_WORSE
        sign = "+" if delta > 0 else ("−" if delta < 0 else " ")
        delta_str = f"{sign}{abs(delta) * 100:5.2f}%"
        man_bar = f"[{color}]{_small_bar(m, sub_w)}[/]"
        sel_bar = f"[{color}]{_small_bar(s, sub_w)}[/]"
        lines.append(
            f"  [{color}]{bucket.capitalize():<13}[/] "
            f" {man_bar} {m*100:5.1f}%   "
            f" {sel_bar} {s*100:5.1f}%   "
            f"[{delta_color}]{delta_str}[/]"
        )
    # Two stacked bars at the bottom for a one-glance comparison.
    lines.append("")
    lines.append(f"  Stacked [b]Manual[/b]:   {_stacked_bar(manual.probs)}")
    lines.append(f"  Stacked [b]Selected[/b]: {_stacked_bar(selected.probs)}")
    return "\n".join(lines)


class ResultsPane(VerticalScroll):
    DEFAULT_CSS = """
    ResultsPane {
        padding: 1 2;
    }
    ResultsPane #status-line {
        height: auto;
        padding-bottom: 1;
    }
    ResultsPane #results-container {
        height: auto;
    }
    ResultsPane #results-tabs {
        height: auto;
    }
    ResultsPane TabPane {
        height: auto;
        padding: 0;
    }
    ResultsPane .tab-body {
        height: auto;
    }
    ResultsPane #comparison-container {
        height: auto;
        border: round $accent;
        padding: 1 2;
        margin-top: 1;
    }
    ResultsPane #comparison-content {
        height: auto;
    }
    ResultsPane .deck-row {
        height: auto;
    }
    ResultsPane .deck-left,
    ResultsPane .deck-right {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    ResultsPane .tab-body > Static {
        height: auto;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._results: list[DeckResult] = []
        self._pool: Pool | None = None
        self._manual_result: DeckResult | None = None
        self._manual_counts: dict[str, int] | None = None
        self._active_result_tab: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(
            "[b]Results[/b] — no run yet. Configure rules & crypt, then press Run.",
            id="status-line",
        )
        yield Vertical(id="results-container")
        with Vertical(id="comparison-container"):
            yield Static(
                "[dim](Manual list vs. selected optimizer result will appear "
                "here once you've entered counts in the Crypt tab and run.)[/]",
                id="comparison-content",
            )
        yield CardArtPanel(id="card-art-panel")

    async def show_results(
        self,
        results: list[DeckResult],
        pool: Pool,
        elapsed_ms: float,
        evaluated: int,
        manual_result: DeckResult | None = None,
        manual_counts: dict[str, int] | None = None,
    ) -> None:
        self._results = list(results)
        self._pool = pool
        self._manual_result = manual_result
        self._manual_counts = manual_counts

        status = self.query_one("#status-line", Static)
        status.update(
            f"[b]Results[/b] — top {len(results)} of {evaluated} decks "
            f"(computed in {elapsed_ms:.1f} ms)."
        )
        container = self.query_one("#results-container", Vertical)
        await container.remove_children()
        if not results:
            await container.mount(Static("No decks found."))
            self._refresh_comparison(active_tab_id=None)
            return
        tabbed = TabbedContent(id="results-tabs")
        await container.mount(tabbed)
        for i, r in enumerate(results, 1):
            title = f"#{i}  P={r.probs['perfect']:.3f}"
            content = Vertical(
                Horizontal(
                    Vertical(Static(_format_optimizer_deck(r, pool)), classes="deck-left"),
                    Vertical(Static(_format_probs(r.probs)), classes="deck-right"),
                    classes="deck-row",
                ),
                Static(_format_outcomes(r)),
                classes="tab-body",
            )
            pane = TabPane(title, content, id=f"result-tab-{i}")
            await tabbed.add_pane(pane)
        if manual_result is not None and manual_counts is not None:
            title = f"Manual List  P={manual_result.probs['perfect']:.3f}"
            content = Vertical(
                Horizontal(
                    Vertical(
                        Static(_format_manual_deck(manual_result, manual_counts, pool)),
                        classes="deck-left",
                    ),
                    Vertical(Static(_format_probs(manual_result.probs)), classes="deck-right"),
                    classes="deck-row",
                ),
                Static(_format_outcomes(manual_result)),
                classes="tab-body",
            )
            pane = TabPane(title, content, id="result-tab-manual")
            await tabbed.add_pane(pane)
        # Initial comparison reflects the active tab (which TabbedContent sets
        # to the first pane).
        self._active_result_tab = tabbed.active or "result-tab-1"
        self._refresh_comparison(active_tab_id=self._active_result_tab)
        # Make sure we're not scrolled past the new content from a previous run.
        self.scroll_home(animate=False)

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        # Only react to the inner results tab strip — the App also listens for
        # outer tab events.
        if event.tabbed_content.id != "results-tabs":
            return
        pane_id = event.pane.id if event.pane is not None else None
        self._active_result_tab = pane_id
        self._refresh_comparison(active_tab_id=pane_id)

    def _refresh_comparison(self, *, active_tab_id: str | None) -> None:
        self._refresh_card_art(active_tab_id=active_tab_id)
        target = self.query_one("#comparison-content", Static)
        if self._manual_result is None:
            target.update(
                "[dim](Manual list vs. selected optimizer result will appear "
                "here once you've entered counts in the Crypt tab and run.)[/]"
            )
            return
        if not self._results:
            target.update("[dim](No optimizer results to compare.)[/]")
            return
        # Resolve which DeckResult the user is currently viewing.
        selected: DeckResult
        selected_label: str
        if active_tab_id == "result-tab-manual" or active_tab_id is None:
            # On the manual tab itself, compare against the optimizer's #1.
            selected = self._results[0]
            selected_label = "Top deck (#1)"
        elif active_tab_id and active_tab_id.startswith("result-tab-"):
            try:
                idx = int(active_tab_id.removeprefix("result-tab-")) - 1
            except ValueError:
                idx = 0
            idx = max(0, min(idx, len(self._results) - 1))
            selected = self._results[idx]
            selected_label = f"#{idx + 1}"
        else:
            selected = self._results[0]
            selected_label = "Top deck (#1)"
        target.update(
            _format_comparison(selected, selected_label, self._manual_result)
        )

    def _refresh_card_art(self, *, active_tab_id: str | None) -> None:
        """Sync the bottom card-art panel with the currently-active inner tab."""
        try:
            panel = self.query_one("#card-art-panel", CardArtPanel)
        except Exception:
            return
        if not self._results and self._manual_result is None:
            return
        if self._pool is None:
            return
        # Resolve the deck to render.
        name_to_count: dict[str, int]
        deck_label: str
        if active_tab_id == "result-tab-manual":
            if self._manual_counts is None:
                return
            name_to_count = dict(self._manual_counts)
            deck_label = "Manual List"
        else:
            if not self._results:
                return
            idx = 0
            if active_tab_id and active_tab_id.startswith("result-tab-"):
                try:
                    idx = int(active_tab_id.removeprefix("result-tab-")) - 1
                except ValueError:
                    idx = 0
                idx = max(0, min(idx, len(self._results) - 1))
            deck_result = self._results[idx]
            # Build name→count from named_lines (uses pool order for anon).
            name_to_count = {
                name: count
                for name, count, _is_anon in deck_result.deck.named_lines(self._pool)
            }
            deck_label = f"#{idx + 1}"
        panel.show_deck(
            name_to_count=name_to_count,
            pool=self._pool,
            deck_label=deck_label,
        )
