# Crypt Calculator

A terminal UI for optimising the opening opening 4 card crypt in the game Vampire the Eternal Struggle.
You describe your crypt deck and the rules that decide whether a hand is
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

**Running inside tmux / zellij / screen?** The auto-probe sees the
multiplexer's emulated terminal — which almost always advertises sixel
support without actually forwarding graphics escapes to the host
terminal — so the app falls back to half-cell rendering automatically
when `$TMUX`, `$ZELLIJ`, or `$STY` is set. Set
`CRYPT_CALCULATOR_RENDERER=auto` to opt back into auto-detection if
your multiplexer is configured to pass graphics through.

If the picked renderer is still wrong (alacritty has been observed to
false-positive on the sixel probe even outside a multiplexer), force
one with the env var:

```sh
CRYPT_CALCULATOR_RENDERER=halfcell uv run crypt-calculator
```

Accepted values: `auto`, `tgp` / `kitty`, `sixel`, `halfcell`,
`unicode`.

[tgp]: https://sw.kovidgoyal.net/kitty/graphics-protocol/
[sixel]: https://en.wikipedia.org/wiki/Sixel

## Examples

Bundled with the package:

- `Anson.{crypt,rules}.yaml`
- `Nehemiah.{crypt,rules}.yaml`
- `unnamed.{crypt,rules}.yaml`

After running **Install examples** they land in
`~/.local/share/crypt-calculator/` and are pickable from the Load
dialogs.

## License

[MIT](LICENSE).
