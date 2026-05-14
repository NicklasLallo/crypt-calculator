from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .pool import MAX_POOL_SIZE, Pool
from .rules import (
    Atom,
    BUCKETS,
    Bucket,
    Clause,
    CountAtLeast,
    CountAtMost,
    CountEquals,
    Rule,
    RuleSet,
    UniqueAtLeast,
)

# The crypt (pool) file format is independent from the rule-set file format,
# so they have independent version numbers.
POOL_VERSION = 1
RULES_VERSION = 2


def load_pool(path: Path) -> Pool:
    """Load just the crypt (names). Counts are ignored — use
    load_pool_with_counts when you also want the manual deck."""
    pool, _ = load_pool_with_counts(path)
    return pool


def load_pool_with_counts(path: Path) -> tuple[Pool, dict[str, int]]:
    """Load both the crypt names and the per-card counts (manual deck).

    Supports two file shapes:
      - new:  ``cards: [{name: X, count: Y}, ...]``  (counts optional per entry)
      - old:  ``names: [X, Y, ...]``                  (no counts)
    """
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    if data.get("version") != POOL_VERSION:
        raise ValueError(f"Unsupported pool file version: {data.get('version')}")
    counts: dict[str, int] = {}
    if "cards" in data:
        cards = data.get("cards") or []
        names = []
        for entry in cards:
            if not isinstance(entry, dict) or "name" not in entry:
                raise ValueError(f"Invalid 'cards' entry: {entry!r}")
            name = entry["name"]
            names.append(name)
            c = entry.get("count")
            if c is not None:
                if not isinstance(c, int) or c < 0:
                    raise ValueError(
                        f"Invalid count for {name!r}: {c!r} (must be non-negative int)"
                    )
                if c > 0:
                    counts[name] = c
    else:
        names = list(data.get("names") or [])
    if len(names) > MAX_POOL_SIZE:
        raise ValueError(f"Pool exceeds max size {MAX_POOL_SIZE}: {len(names)} names")
    return Pool(names=names), counts


def save_pool(pool: Pool, path: Path, counts: dict[str, int] | None = None) -> None:
    """Save the crypt (and optional manual-deck counts) as YAML."""
    counts = counts or {}
    cards: list[dict[str, object]] = []
    for name in pool.names:
        entry: dict[str, object] = {"name": name}
        c = counts.get(name, 0)
        if c > 0:
            entry["count"] = c
        cards.append(entry)
    data = {"version": POOL_VERSION, "cards": cards}
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def _atom_to_dict(atom: Atom) -> dict[str, Any]:
    if isinstance(atom, CountAtLeast):
        return {"type": "count_at_least", "card": atom.card, "k": atom.k}
    if isinstance(atom, CountAtMost):
        return {"type": "count_at_most", "card": atom.card, "k": atom.k}
    if isinstance(atom, CountEquals):
        return {"type": "count_equals", "card": atom.card, "k": atom.k}
    if isinstance(atom, UniqueAtLeast):
        return {"type": "unique_at_least", "k": atom.k, "excluding": sorted(atom.excluding)}
    raise TypeError(f"Unknown atom type: {type(atom).__name__}")


def _atom_from_dict(d: dict[str, Any]) -> Atom:
    t = d.get("type")
    if t == "count_at_least":
        return CountAtLeast(card=d["card"], k=int(d["k"]))
    if t == "count_at_most":
        return CountAtMost(card=d["card"], k=int(d["k"]))
    if t == "count_equals":
        return CountEquals(card=d["card"], k=int(d["k"]))
    if t == "unique_at_least":
        excluding = frozenset(d.get("excluding") or [])
        return UniqueAtLeast(k=int(d["k"]), excluding=excluding)
    raise ValueError(f"Unknown atom type: {t!r}")


def _rule_to_dict(rule: Rule) -> dict[str, Any]:
    return {"clauses": [{"any": [_atom_to_dict(a) for a in clause]} for clause in rule]}


def _rule_from_dict(d: dict[str, Any]) -> Rule:
    clauses_data = d.get("clauses") or []
    rule: Rule = []
    for clause_dict in clauses_data:
        atoms = [_atom_from_dict(a) for a in (clause_dict.get("any") or [])]
        rule.append(atoms)
    return rule


def save_ruleset(rules: RuleSet, path: Path) -> None:
    data: dict[str, Any] = {
        "version": RULES_VERSION,
        "default": rules.default,
        "perfect": [_rule_to_dict(r) for r in rules.perfect],
        "good": [_rule_to_dict(r) for r in rules.good],
        "acceptable": [_rule_to_dict(r) for r in rules.acceptable],
    }
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def load_ruleset(
    path: Path, pool: Pool | None = None
) -> tuple[RuleSet, str | None]:
    """Load a rule-set YAML. Returns (ruleset, optional migration note).

    Supports two versions:
      - v2 (current): perfect/good/acceptable keys.
      - v1 (legacy): perfect/acceptable/unacceptable. The unacceptable list is
        dropped on load (it's redundant with the catch-all default bucket); the
        caller is given a one-line note so it can flash a warning. Saving the
        resulting RuleSet writes v2.
    """
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    version = data.get("version")
    note: str | None = None
    if version == RULES_VERSION:
        good_list = [_rule_from_dict(r) for r in (data.get("good") or [])]
        unacc_in_v2 = data.get("unacceptable") or []
        if unacc_in_v2:
            note = (
                f"Ignoring {len(unacc_in_v2)} 'unacceptable' rule(s) — that "
                "bucket is now implicit (default for hands that don't match)."
            )
    elif version == 1:
        good_list = []
        dropped = len(data.get("unacceptable") or [])
        if dropped:
            note = (
                f"Migrated from v1: dropped {dropped} 'unacceptable' rule(s) "
                "(now the implicit default bucket). Save to upgrade the file."
            )
        else:
            note = "Migrated from v1 (no unacceptable rules to drop)."
    else:
        raise ValueError(f"Unsupported rules file version: {version}")

    default = data.get("default", "unacceptable")
    if default not in BUCKETS:
        raise ValueError(f"Invalid default bucket: {default!r}")
    rs = RuleSet(
        perfect=[_rule_from_dict(r) for r in (data.get("perfect") or [])],
        good=good_list,
        acceptable=[_rule_from_dict(r) for r in (data.get("acceptable") or [])],
        default=default,  # type: ignore[arg-type]
    )
    if pool is not None:
        missing = rs.referenced_cards() - set(pool.names)
        if missing:
            raise ValueError(
                f"Rule set references cards not in pool: {sorted(missing)}"
            )
    return rs, note
