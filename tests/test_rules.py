from __future__ import annotations

from crypt_calculator.rules import (
    CountAtLeast,
    CountAtMost,
    CountEquals,
    Hand,
    RuleSet,
    UniqueAtLeast,
    evaluate_rule,
)


def hand(referenced: dict[str, int] | None = None, anon: tuple[int, ...] = ()) -> Hand:
    return Hand(referenced=referenced or {}, anon_draws=anon)


def test_count_at_least():
    h = hand({"G": 2})
    assert CountAtLeast("G", 1).evaluate(h)
    assert CountAtLeast("G", 2).evaluate(h)
    assert not CountAtLeast("G", 3).evaluate(h)


def test_count_at_most():
    h = hand({"G": 2})
    assert CountAtMost("G", 2).evaluate(h)
    assert not CountAtMost("G", 1).evaluate(h)


def test_count_equals():
    h = hand({"G": 0})
    assert CountEquals("G", 0).evaluate(h)
    assert not CountEquals("G", 1).evaluate(h)


def test_unique_at_least_includes_anon():
    h = hand({"G": 2}, anon=(1, 1))
    assert UniqueAtLeast(3).evaluate(h)  # G + 2 anon = 3 unique
    assert not UniqueAtLeast(4).evaluate(h)


def test_unique_excluding_referenced():
    h = hand({"G": 2}, anon=(1, 1))
    # Excluding G leaves only the 2 anon types
    assert UniqueAtLeast(2, frozenset({"G"})).evaluate(h)
    assert not UniqueAtLeast(3, frozenset({"G"})).evaluate(h)


def test_cnf_rule_and_of_or():
    # (>=1 G OR >=1 A) AND (>=1 unique excluding {G, A})
    rule = [
        [CountAtLeast("G", 1), CountAtLeast("A", 1)],
        [UniqueAtLeast(1, frozenset({"G", "A"}))],
    ]
    assert evaluate_rule(rule, hand({"G": 1, "A": 0}, anon=(1,)))  # G + anon
    assert evaluate_rule(rule, hand({"G": 0, "A": 1}, anon=(2,)))  # A + anon
    assert not evaluate_rule(rule, hand({"G": 0, "A": 0}, anon=(4,)))  # neither
    assert not evaluate_rule(rule, hand({"G": 2, "A": 0}, anon=()))  # no anon


def test_ruleset_bucket_priority():
    """Perfect > Good > Acceptable > default."""
    rules = RuleSet(
        perfect=[[[CountAtLeast("G", 3)]]],
        good=[[[CountAtLeast("G", 2)]]],
        acceptable=[[[CountAtLeast("G", 1)]]],
    )
    assert rules.classify(hand({"G": 3})) == "perfect"
    assert rules.classify(hand({"G": 2})) == "good"
    assert rules.classify(hand({"G": 1})) == "acceptable"
    assert rules.classify(hand({"G": 0})) == "unacceptable"  # default


def test_good_wins_over_acceptable_on_overlap():
    """If both Good and Acceptable rules match, Good wins."""
    rules = RuleSet(
        good=[[[CountAtLeast("G", 1)]]],
        acceptable=[[[CountAtLeast("G", 1)]]],
    )
    assert rules.classify(hand({"G": 1})) == "good"


def test_ruleset_is_empty():
    assert RuleSet().is_empty()
    assert not RuleSet(perfect=[[[CountAtLeast("G", 1)]]]).is_empty()
    assert not RuleSet(good=[[[CountAtLeast("G", 1)]]]).is_empty()
    assert not RuleSet(acceptable=[[[CountAtLeast("G", 1)]]]).is_empty()


def test_ruleset_referenced_cards():
    rules = RuleSet(
        perfect=[
            [[CountAtLeast("G", 1)], [UniqueAtLeast(2, frozenset({"G", "A"}))]],
        ],
        good=[[[CountAtLeast("B", 1)]]],
        acceptable=[[[CountAtLeast("C", 1)]]],
    )
    assert rules.referenced_cards() == {"G", "A", "B", "C"}
