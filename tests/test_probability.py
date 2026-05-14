from __future__ import annotations

from crypt_calculator.deck import Deck
from crypt_calculator.probability import bucket_probabilities, _bucket_breakdown
from crypt_calculator.rules import (
    BUCKETS,
    CountAtLeast,
    RuleSet,
    UniqueAtLeast,
)


def _approx(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) < tol


def test_bucket_probs_sum_to_one():
    # Several decks; check that probs sum to 1 regardless of rules
    rules = RuleSet(
        perfect=[[[CountAtLeast("G", 1)], [UniqueAtLeast(2, frozenset({"G"}))]]],
    )
    decks = [
        Deck(referenced={"G": 0}, anon=(12,)),
        Deck(referenced={"G": 4}, anon=(1, 1, 1, 1, 1, 1, 1, 1)),
        Deck(referenced={"G": 6}, anon=(3, 2, 1)),
        Deck(referenced={"G": 1}, anon=(11,)),
    ]
    for deck in decks:
        probs = bucket_probabilities(deck, rules)
        assert _approx(sum(probs.values()), 1.0), (deck, probs)


def test_goratrix_g4_unique_singletons():
    """Worked example: 4 Goratrix + 8 distinct non-G singletons, two-tier rules.

    Perfect = >=1 G AND >=2 unique non-G
    Acceptable = >=1 G AND >=1 unique non-G
    Anything else falls into the default Unacceptable bucket (no explicit
    unacceptable rules — 0G or 4G hands no longer match Perfect/Acceptable and
    so land in the default).
    """
    rules = RuleSet(
        perfect=[[[CountAtLeast("G", 1)], [UniqueAtLeast(2, frozenset({"G"}))]]],
        acceptable=[[[CountAtLeast("G", 1)], [UniqueAtLeast(1, frozenset({"G"}))]]],
    )
    deck = Deck(referenced={"G": 4}, anon=(1, 1, 1, 1, 1, 1, 1, 1))
    probs = bucket_probabilities(deck, rules)
    # All four bucket keys are present
    assert set(probs.keys()) == set(BUCKETS)
    # P(Perfect) ≈ 0.792 (from plan table)
    assert 0.79 < probs["perfect"] < 0.80
    # Good is unused (no rules) → exactly 0
    assert probs["good"] == 0
    # P(Acceptable) covers the 3G case (~0.0646)
    assert 0.06 < probs["acceptable"] < 0.07
    # Unacceptable: P(0G) + P(4G) ≈ 0.141 + 0.002 ≈ 0.143
    assert 0.14 < probs["unacceptable"] < 0.15
    assert _approx(sum(probs.values()), 1.0)


def test_good_bucket_populated():
    """Three-tier rules — verify Good appears in the breakdown."""
    rules = RuleSet(
        perfect=[[[CountAtLeast("G", 3)]]],
        good=[[[CountAtLeast("G", 2)]]],
        acceptable=[[[CountAtLeast("G", 1)]]],
    )
    # Mostly G deck so we hit each tier with some non-trivial probability.
    deck = Deck(referenced={"G": 6}, anon=(1, 1, 1, 1, 1, 1))
    probs = bucket_probabilities(deck, rules)
    assert probs["good"] > 0
    assert probs["perfect"] > 0
    assert probs["acceptable"] > 0
    assert _approx(sum(probs.values()), 1.0)


def test_single_type_deck_all_quads():
    # Deck of 12 copies of one referenced card: every draw is "4 of that card".
    rules = RuleSet(
        perfect=[[[CountAtLeast("X", 4)]]],
    )
    deck = Deck(referenced={"X": 12}, anon=())
    probs = bucket_probabilities(deck, rules)
    assert _approx(probs["perfect"], 1.0)


def test_no_rules_default_unacceptable():
    rules = RuleSet()  # default 'unacceptable'
    deck = Deck(referenced={}, anon=(1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1))
    probs = bucket_probabilities(deck, rules)
    assert _approx(probs["unacceptable"], 1.0)


def test_outcome_breakdown_sums_to_one():
    rules = RuleSet(
        perfect=[[[CountAtLeast("G", 1)], [UniqueAtLeast(2, frozenset({"G"}))]]],
    )
    deck = Deck(referenced={"G": 4}, anon=(1, 1, 1, 1, 1, 1, 1, 1))
    _, outcomes = _bucket_breakdown(deck, rules)
    assert _approx(sum(p for _, _, p in outcomes), 1.0)
