from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from .pool import Pool


@dataclass(frozen=True)
class Deck:
    """A deck represented in canonical form for the optimizer.

    - referenced: counts of named cards that appear in the rule set. These names
      are kept distinct from each other.
    - anon: a sorted-descending partition of the remaining cards. Each entry is
      the count of one distinct unreferenced card type. (Optionally, the user
      can later "pin" specific pool names to these slots; that does not change
      probabilities.)
    """

    referenced: Mapping[str, int]
    anon: tuple[int, ...]

    @property
    def size(self) -> int:
        return sum(self.referenced.values()) + sum(self.anon)

    @property
    def types(self) -> int:
        return sum(1 for c in self.referenced.values() if c > 0) + len(self.anon)

    def __post_init__(self) -> None:
        # ensure anon is sorted descending and contains only positive counts
        anon = tuple(self.anon)
        if any(c <= 0 for c in anon):
            raise ValueError(f"anon partition must contain positive counts only, got {anon}")
        if list(anon) != sorted(anon, reverse=True):
            raise ValueError(f"anon partition must be sorted descending, got {anon}")

    def describe(self, anon_label: str = "other card") -> list[str]:
        """Render a human-readable line per card group. (Anon slots are
        unnamed.) Prefer named_lines() when a Pool is available."""
        lines = [f"{count} × {name}" for name, count in self.referenced.items() if count > 0]
        for c in self.anon:
            if c == 1:
                lines.append(f"1 × (a distinct {anon_label})")
            else:
                lines.append(f"{c} × (a distinct {anon_label})")
        return lines

    def named_lines(self, pool: "Pool") -> list[tuple[str, int, bool]]:
        """Return [(name, count, is_anon_filled), …] in *pool order*.

        Anon partition entries (sorted descending by count) are assigned to
        unreferenced pool names in pool order — so the highest-priority
        unreferenced card claims the largest anon slot, breaking ties by
        position in the crypt. The ``is_anon_filled`` flag distinguishes
        names auto-filled this way from cards that appear explicitly because
        they're referenced by the rule set.
        """
        referenced_names = set(self.referenced.keys())
        unreferenced_in_pool = [n for n in pool.names if n not in referenced_names]
        anon_assignment: dict[str, int] = {}
        for i, count in enumerate(self.anon):
            if i < len(unreferenced_in_pool):
                anon_assignment[unreferenced_in_pool[i]] = count

        out: list[tuple[str, int, bool]] = []
        for name in pool.names:
            if name in referenced_names:
                c = self.referenced.get(name, 0)
                if c > 0:
                    out.append((name, c, False))
            elif name in anon_assignment:
                out.append((name, anon_assignment[name], True))
        return out
