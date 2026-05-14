from __future__ import annotations

from math import comb
from typing import Iterator

from .deck import Deck
from .rules import BUCKETS, Bucket, Hand, RuleSet

HAND_SIZE = 4


def _enumerate_draws(
    categories: list[tuple[str | None, int]],
    draws_left: int,
    index: int = 0,
    accum: list[int] | None = None,
) -> Iterator[list[int]]:
    """Yield every draw vector (one count per category) summing to draws_left.

    Each category has a maximum equal to the deck count for that category.
    """
    accum = accum if accum is not None else []
    if index == len(categories):
        if draws_left == 0:
            yield list(accum)
        return
    _, deck_count = categories[index]
    upper = min(deck_count, draws_left)
    accum.append(0)
    for k in range(upper + 1):
        accum[-1] = k
        yield from _enumerate_draws(categories, draws_left - k, index + 1, accum)
    accum.pop()


def _build_hand(
    categories: list[tuple[str | None, int]],
    draws: list[int],
) -> Hand:
    referenced: dict[str, int] = {}
    anon_draws: list[int] = []
    for (name, _), k in zip(categories, draws):
        if name is None:
            if k > 0:
                anon_draws.append(k)
        else:
            referenced[name] = k
    anon_draws.sort(reverse=True)
    return Hand(referenced=referenced, anon_draws=tuple(anon_draws))


def _draw_prob_numerator(categories: list[tuple[str | None, int]], draws: list[int]) -> int:
    product = 1
    for (_, deck_count), k in zip(categories, draws):
        product *= comb(deck_count, k)
    return product


def bucket_probabilities(deck: Deck, rules: RuleSet) -> dict[Bucket, float]:
    """Return P(bucket) for each bucket, summing to 1.0."""
    return _bucket_breakdown(deck, rules)[0]


def _bucket_breakdown(
    deck: Deck,
    rules: RuleSet,
) -> tuple[dict[Bucket, float], list[tuple[Hand, Bucket, float]]]:
    """Return (bucket probabilities, list of (hand, bucket, P(hand)) outcomes)."""
    N = deck.size
    if N < HAND_SIZE:
        raise ValueError(f"Deck size {N} is below hand size {HAND_SIZE}")
    denom = comb(N, HAND_SIZE)
    categories: list[tuple[str | None, int]] = []
    # Referenced categories: include zero-count entries too (so that Hand.referenced
    # always carries every referenced name)
    for name, count in deck.referenced.items():
        categories.append((name, count))
    for c in deck.anon:
        categories.append((None, c))

    probs: dict[Bucket, float] = {b: 0.0 for b in BUCKETS}
    outcomes: dict[tuple, tuple[Hand, Bucket, float]] = {}
    for draws in _enumerate_draws(categories, HAND_SIZE):
        numerator = _draw_prob_numerator(categories, draws)
        if numerator == 0:
            continue
        p = numerator / denom
        hand = _build_hand(categories, draws)
        bucket = rules.classify(hand)
        probs[bucket] += p
        # Deduplicate outcomes that look identical to the user (same referenced
        # counts + same anon_draws shape).
        key = (tuple(sorted(hand.referenced.items())), hand.anon_draws, bucket)
        if key in outcomes:
            prev_hand, prev_bucket, prev_p = outcomes[key]
            outcomes[key] = (prev_hand, prev_bucket, prev_p + p)
        else:
            outcomes[key] = (hand, bucket, p)
    return probs, sorted(outcomes.values(), key=lambda t: -t[2])
