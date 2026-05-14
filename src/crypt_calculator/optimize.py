from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Literal

from .deck import Deck
from .pool import Pool
from .probability import _bucket_breakdown
from .rules import BUCKETS, Bucket, Hand, RuleSet

ObjectiveKind = Literal["max_perfect", "max_pg", "max_pga", "weighted"]

DEFAULT_WEIGHTS: tuple[float, float, float, float] = (5.0, 4.0, 3.0, 0.0)  # P, G, A, U


@dataclass(frozen=True)
class Objective:
    """An optimization target.

    For lex objectives (``max_perfect`` / ``max_pg`` / ``max_pga``) the
    ``weights`` field is ignored. For ``weighted``, the weights are applied
    to P, G, A, U respectively.
    """

    kind: ObjectiveKind = "max_perfect"
    weights: tuple[float, float, float, float] = DEFAULT_WEIGHTS


@dataclass
class DeckResult:
    deck: Deck
    probs: dict[Bucket, float]
    outcomes: list[tuple[Hand, Bucket, float]]
    score: tuple[float, ...]


def _compositions(total: int, num_parts: int) -> Iterator[tuple[int, ...]]:
    if num_parts == 0:
        if total == 0:
            yield ()
        return
    if num_parts == 1:
        yield (total,)
        return
    for first in range(total + 1):
        for rest in _compositions(total - first, num_parts - 1):
            yield (first,) + rest


def _partitions(total: int, max_parts: int, max_value: int | None = None) -> Iterator[tuple[int, ...]]:
    if total == 0:
        yield ()
        return
    if max_parts == 0:
        return
    cap = total if max_value is None else min(total, max_value)
    for v in range(cap, 0, -1):
        for rest in _partitions(total - v, max_parts - 1, v):
            yield (v,) + rest


def _score(probs: dict[Bucket, float], objective: Objective) -> tuple[float, ...]:
    p = probs.get("perfect", 0.0)
    g = probs.get("good", 0.0)
    a = probs.get("acceptable", 0.0)
    u = probs.get("unacceptable", 0.0)
    if objective.kind == "max_perfect":
        return (p, p + g, p + g + a, -u)
    if objective.kind == "max_pg":
        return (p + g, p, p + g + a, -u)
    if objective.kind == "max_pga":
        return (p + g + a, p + g, p, -u)
    # weighted
    wp, wg, wa, wu = objective.weights
    return (wp * p + wg * g + wa * a + wu * u,)


def optimize(
    pool: Pool,
    rules: RuleSet,
    size_min: int = 12,
    size_max: int = 14,
    objective: Objective | None = None,
    top_k: int = 10,
) -> tuple[list[DeckResult], int]:
    """Enumerate decks and return (top_k results, total decks evaluated)."""
    objective = objective or Objective()
    referenced = sorted(rules.referenced_cards())
    for name in referenced:
        if not pool.has(name):
            raise ValueError(f"Rule references card {name!r} not in pool")
    R = len(referenced)
    anon_max_parts = pool.size() - R

    results: list[DeckResult] = []
    evaluated = 0
    for N in range(size_min, size_max + 1):
        for total_ref in range(N + 1):
            for ref_counts in _compositions(total_ref, R):
                remainder = N - total_ref
                for partition in _partitions(remainder, anon_max_parts):
                    ref_dict = dict(zip(referenced, ref_counts))
                    deck = Deck(referenced=ref_dict, anon=partition)
                    probs, outcomes = _bucket_breakdown(deck, rules)
                    results.append(
                        DeckResult(
                            deck=deck,
                            probs=probs,
                            outcomes=outcomes,
                            score=_score(probs, objective),
                        )
                    )
                    evaluated += 1
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k], evaluated


def search_space_breakdown(
    pool: Pool, rules: RuleSet, size_min: int, size_max: int
) -> dict[int, int]:
    """Per-deck-size count of distinct decks the optimizer would visit."""
    R = len(rules.referenced_cards())
    anon_max_parts = pool.size() - R
    out: dict[int, int] = {}
    for N in range(size_min, size_max + 1):
        total = 0
        for total_ref in range(N + 1):
            count_comps = sum(1 for _ in _compositions(total_ref, R)) if R or total_ref == 0 else 0
            count_parts = sum(1 for _ in _partitions(N - total_ref, anon_max_parts))
            total += count_comps * count_parts
        out[N] = total
    return out


def count_search_space(pool: Pool, rules: RuleSet, size_min: int, size_max: int) -> int:
    """Estimate the number of distinct decks the brute-force optimizer will visit.

    Useful for the TUI to decide whether to switch to a heuristic. Cheap to compute.
    """
    return sum(search_space_breakdown(pool, rules, size_min, size_max).values())
