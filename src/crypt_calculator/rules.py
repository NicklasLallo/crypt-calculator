from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union

Bucket = Literal["perfect", "good", "acceptable", "unacceptable"]
BUCKETS: tuple[Bucket, ...] = ("perfect", "good", "acceptable", "unacceptable")
# Buckets that the user can attach rules to (everything but the implicit default).
RULE_BUCKETS: tuple[Bucket, ...] = ("perfect", "good", "acceptable")


@dataclass(frozen=True)
class Hand:
    """A 4-card draw, decomposed for rule evaluation.

    - referenced: counts drawn for every card referenced anywhere in the rule
      set (including via UniqueAtLeast.excluding). Cards not drawn have count 0.
    - anon_draws: counts drawn from each distinct unreferenced card type; zero
      counts are omitted. (E.g. if the deck has 6 unreferenced types but only
      two of them contributed to the hand, anon_draws has length 2.)
    """

    referenced: dict[str, int]
    anon_draws: tuple[int, ...]

    def total(self) -> int:
        return sum(self.referenced.values()) + sum(self.anon_draws)

    def unique_count(self, excluding: frozenset[str] = frozenset()) -> int:
        ref_unique = sum(1 for name, count in self.referenced.items()
                         if count > 0 and name not in excluding)
        anon_unique = sum(1 for c in self.anon_draws if c > 0)
        return ref_unique + anon_unique


@dataclass(frozen=True)
class CountAtLeast:
    card: str
    k: int

    def evaluate(self, hand: Hand) -> bool:
        return hand.referenced.get(self.card, 0) >= self.k

    def referenced_cards(self) -> set[str]:
        return {self.card}


@dataclass(frozen=True)
class CountAtMost:
    card: str
    k: int

    def evaluate(self, hand: Hand) -> bool:
        return hand.referenced.get(self.card, 0) <= self.k

    def referenced_cards(self) -> set[str]:
        return {self.card}


@dataclass(frozen=True)
class CountEquals:
    card: str
    k: int

    def evaluate(self, hand: Hand) -> bool:
        return hand.referenced.get(self.card, 0) == self.k

    def referenced_cards(self) -> set[str]:
        return {self.card}


@dataclass(frozen=True)
class UniqueAtLeast:
    k: int
    excluding: frozenset[str] = frozenset()

    def evaluate(self, hand: Hand) -> bool:
        return hand.unique_count(self.excluding) >= self.k

    def referenced_cards(self) -> set[str]:
        return set(self.excluding)


Atom = Union[CountAtLeast, CountAtMost, CountEquals, UniqueAtLeast]
Clause = list[Atom]  # OR semantics
Rule = list[Clause]  # AND semantics


def evaluate_rule(rule: Rule, hand: Hand) -> bool:
    return all(any(atom.evaluate(hand) for atom in clause) for clause in rule)


def rule_referenced_cards(rule: Rule) -> set[str]:
    cards: set[str] = set()
    for clause in rule:
        for atom in clause:
            cards.update(atom.referenced_cards())
    return cards


@dataclass
class RuleSet:
    perfect: list[Rule] = field(default_factory=list)
    good: list[Rule] = field(default_factory=list)
    acceptable: list[Rule] = field(default_factory=list)
    default: Bucket = "unacceptable"

    def classify(self, hand: Hand) -> Bucket:
        if any(evaluate_rule(r, hand) for r in self.perfect):
            return "perfect"
        if any(evaluate_rule(r, hand) for r in self.good):
            return "good"
        if any(evaluate_rule(r, hand) for r in self.acceptable):
            return "acceptable"
        return self.default

    def referenced_cards(self) -> set[str]:
        cards: set[str] = set()
        for bucket_rules in (self.perfect, self.good, self.acceptable):
            for rule in bucket_rules:
                cards.update(rule_referenced_cards(rule))
        return cards

    def is_empty(self) -> bool:
        return not (self.perfect or self.good or self.acceptable)
