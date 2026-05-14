from __future__ import annotations

from pathlib import Path

from crypt_calculator.io import load_pool, load_ruleset
from crypt_calculator.optimize import (
    DEFAULT_WEIGHTS,
    Objective,
    count_search_space,
    optimize,
)
from crypt_calculator.pool import Pool
from crypt_calculator.rules import (
    CountAtLeast,
    RuleSet,
    UniqueAtLeast,
)

EXAMPLES = Path(__file__).resolve().parent / "data"


# A 2-tier rule set for the worked-example arithmetic: Perfect = >=1G AND >=2
# unique non-G; Acceptable = >=1G AND >=1 unique non-G. Hands that don't match
# fall into the default Unacceptable bucket (no explicit unacceptable rules).
GORATRIX_RULES_2TIER = RuleSet(
    perfect=[
        [[CountAtLeast("Goratrix", 1)], [UniqueAtLeast(2, frozenset({"Goratrix"}))]],
    ],
    acceptable=[
        [[CountAtLeast("Goratrix", 1)], [UniqueAtLeast(1, frozenset({"Goratrix"}))]],
    ],
)


def test_goratrix_with_full_pool_matches_worked_example():
    """With pool of 9+ names (8 non-Goratrix), the worked example optimum is 4G
    + 8 unique non-G singletons, P(Perfect) ≈ 0.792."""
    pool = Pool(names=["Goratrix"] + [f"NG{i}" for i in range(9)])
    results, _ = optimize(pool, GORATRIX_RULES_2TIER, size_min=12, size_max=12, top_k=3)
    best = results[0]
    assert best.deck.referenced["Goratrix"] == 4
    assert best.deck.anon == (1, 1, 1, 1, 1, 1, 1, 1)
    assert 0.79 < best.probs["perfect"] < 0.80


def test_shipped_goratrix_3tier_yaml():
    """The shipped Goratrix YAML uses a 3-tier gradient (Perfect/Good/Acceptable).
    Verify each tier is populated and the optimizer produces sane top-3."""
    pool = load_pool(EXAMPLES / "goratrix.crypt.yaml")
    rules, _ = load_ruleset(EXAMPLES / "goratrix.rules.yaml", pool)
    assert len(rules.perfect) == 1
    assert len(rules.good) == 1
    assert len(rules.acceptable) == 1
    results, _ = optimize(pool, rules, size_min=12, size_max=12, top_k=3)
    best = results[0]
    # Per the 3-tier gradient, P(Perfect ∪ Good ∪ Acceptable) ≤ 1 and decreasing
    # by tier:
    p = best.probs["perfect"]
    g = best.probs["good"]
    a = best.probs["acceptable"]
    u = best.probs["unacceptable"]
    assert abs(p + g + a + u - 1.0) < 1e-9
    assert p + g + a > 0.5


def test_all_quads_deck():
    pool = Pool(names=["X", "Y", "Z"])
    rules = RuleSet(perfect=[[[CountAtLeast("X", 4)]]])
    results, _ = optimize(pool, rules, size_min=12, size_max=12, top_k=3)
    best = results[0]
    assert best.deck.referenced["X"] == 12
    assert best.deck.anon == ()
    assert best.probs["perfect"] > 0.99


def test_max_unique_no_named():
    """No referenced cards (only structural UniqueAtLeast)."""
    pool = Pool(names=[f"C{i}" for i in range(10)])
    rules = RuleSet(perfect=[[[UniqueAtLeast(4)]]])
    results, _ = optimize(pool, rules, size_min=12, size_max=12, top_k=3)
    best = results[0]
    assert best.deck.size == 12
    assert sum(best.deck.anon) == 12
    assert len(best.deck.anon) == 10
    assert 0.81 < best.probs["perfect"] < 0.83


def test_search_space_count_is_sensible():
    pool = load_pool(EXAMPLES / "goratrix.crypt.yaml")
    rules, _ = load_ruleset(EXAMPLES / "goratrix.rules.yaml", pool)
    n = count_search_space(pool, rules, 12, 14)
    assert 100 < n < 10_000


def test_four_objectives_run_and_are_consistent():
    """Each objective should produce a top result; tiers are ordered:
    top P ≤ top P+G ≤ top P+G+A; and weighted with default weights ≥ 0."""
    pool = load_pool(EXAMPLES / "goratrix.crypt.yaml")
    rules, _ = load_ruleset(EXAMPLES / "goratrix.rules.yaml", pool)

    def best_of(kind: str):
        obj = Objective(kind=kind)  # type: ignore[arg-type]
        results, _ = optimize(pool, rules, 12, 12, objective=obj, top_k=1)
        return results[0]

    a = best_of("max_perfect")
    b = best_of("max_pg")
    c = best_of("max_pga")
    # Each "top" optimizes its own metric — by construction the best score on a
    # wider union is at least the best on a narrower one.
    top_p = a.probs["perfect"]
    top_pg = b.probs["perfect"] + b.probs["good"]
    top_pga = c.probs["perfect"] + c.probs["good"] + c.probs["acceptable"]
    assert top_pg >= top_p - 1e-9
    assert top_pga >= top_pg - 1e-9

    # Weighted with default weights (5,4,3,0): score should equal the dot
    # product. Sanity check that the returned score matches.
    w = Objective(kind="weighted", weights=DEFAULT_WEIGHTS)
    results, _ = optimize(pool, rules, 12, 12, objective=w, top_k=1)
    d = results[0]
    expected = (
        DEFAULT_WEIGHTS[0] * d.probs["perfect"]
        + DEFAULT_WEIGHTS[1] * d.probs["good"]
        + DEFAULT_WEIGHTS[2] * d.probs["acceptable"]
        + DEFAULT_WEIGHTS[3] * d.probs["unacceptable"]
    )
    assert abs(d.score[0] - expected) < 1e-9


def test_weighted_with_negative_unacceptable_penalty():
    """A penalty on Unacceptable shifts the optimum away from high-U decks."""
    pool = load_pool(EXAMPLES / "goratrix.crypt.yaml")
    rules, _ = load_ruleset(EXAMPLES / "goratrix.rules.yaml", pool)
    zero_u_weight = Objective(kind="weighted", weights=(5.0, 4.0, 3.0, 0.0))
    penalty_u_weight = Objective(kind="weighted", weights=(5.0, 4.0, 3.0, -10.0))
    r0, _ = optimize(pool, rules, 12, 12, objective=zero_u_weight, top_k=1)
    rP, _ = optimize(pool, rules, 12, 12, objective=penalty_u_weight, top_k=1)
    # With a -10 penalty on U, the winning deck must have U ≤ winning U at 0.
    assert rP[0].probs["unacceptable"] <= r0[0].probs["unacceptable"] + 1e-9
