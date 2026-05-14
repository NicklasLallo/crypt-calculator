# Crypt Calculator

A terminal UI for optimising the opening hand in a 4-card-draw card game.
You describe your card pool and the rules that decide whether a hand is
*perfect / good / acceptable / unacceptable*, and the optimiser searches
every legal deck for the one with the best odds.

## What it does

- **Probability engine** — exact enumeration of every 4-card hand from any
  deck composition, classified into outcome buckets by your rules.
- **Optimiser** — searches over deck size and composition for the best
  decks under one of four objectives (max P, max P∪G, max P∪G∪A, or a
  weighted sum). Returns the top-K results so you can compare them.
- **Manual deck** — enter your own counts on the Crypt tab and the tool
  evaluates them alongside the optimiser's picks, with a side-by-side
  comparison panel.
- **Card art** — thumbnails next to each crypt entry and full art for the
  selected deck, fetched lazily from [krcg.org][krcg] and cached locally.

[krcg]: https://static.krcg.org

## Screenshot

*Results tab after running the bundled Anson example — top decks,
draw-outcome breakdown, side-by-side comparison against the user's
manual deck, and card art for the selected result.*

![Results tab — Anson example](resources/ExampleResult.jpg)

## Install

Uses [uv](https://docs.astral.sh/uv/) for environment management; install
that first if you don't have it.

```sh
git clone https://github.com/NicklasLallo/crypt-calculator.git
cd crypt-calculator
uv sync
uv run crypt-calculator
```

Requires Python 3.12+. Card art rendering uses
[textual-image](https://github.com/lnqs/textual-image); your terminal
needs to support either the [Kitty graphics protocol][tgp] or
[Sixel][sixel] for actual images (Kitty, WezTerm, recent Konsole,
foot, ghostty). Other terminals fall back to a Unicode half-cell preview.

[tgp]: https://sw.kovidgoyal.net/kitty/graphics-protocol/
[sixel]: https://en.wikipedia.org/wiki/Sixel

## First run

On launch the app offers to copy the bundled example crypts +
rule-sets to your data directory (`$XDG_DATA_HOME/crypt-calculator`,
defaulting to `~/.local/share/crypt-calculator`). Accept and you'll have
ready-made examples to load from the Crypt and Rules tabs.

You can rerun the install any time via the **Install examples** button
on the Crypt tab.

## Usage

1. **Crypt tab** — type up to 10 card names. Enter per-card counts in
   the `#` column to define your *manual deck* (the optimiser compares
   against this).
2. **Rules tab** — author *perfect*, *good*, and *acceptable* rules.
   Anything not matched falls into the implicit *unacceptable* bucket.
3. **Run tab** — pick deck-size bounds and an objective, press one of
   the four run buttons (or Ctrl+1 … Ctrl+4).
4. **Results tab** — top-K decks, draw-outcome breakdown, manual-deck
   comparison, and card art for whichever tab is selected.

`Ctrl+E` / `Ctrl+W` cycle through tabs; `Ctrl+O` / `Ctrl+S` load/save on
the active tab.

## Examples

Bundled with the package:

- `Anson.{crypt,rules}.yaml` — five-vampire Anson stinger with a
  vote-based win rule.
- `Nehemiah.{crypt,rules}.yaml`
- `unnamed.{crypt,rules}.yaml`

After running **Install examples** they land in
`~/.local/share/crypt-calculator/` and are pickable from the Load
dialogs.

## Development

```sh
uv sync
uv run pytest             # 51 tests, ~0.6s
uv run crypt-calculator   # launch the TUI
```

Layout:

```
src/crypt_calculator/
├── app.py            # the Textual App + tab wiring
├── pool.py           # Pool dataclass (10 named slots, uniqueness)
├── rules.py          # Rule primitives + RuleSet evaluation
├── deck.py           # Deck = referenced counts + anonymous bucket
├── probability.py    # exact enumeration of 4-card hands
├── optimize.py       # search over decks + objectives
├── io.py             # YAML load/save (v1/v2 migration)
├── userdata.py       # XDG data/config + first-run state
├── examples/         # bundled .crypt.yaml / .rules.yaml
└── screens/          # Textual panes: pool, rules, run, results,
                      # filepicker, card_image, card_art, widgets
tests/
├── data/             # test fixtures (goratrix)
└── test_*.py
```

## License

[MIT](LICENSE).
