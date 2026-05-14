from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crypt_calculator.io import (
    load_pool,
    load_pool_with_counts,
    load_ruleset,
    save_pool,
    save_ruleset,
)
from crypt_calculator.pool import Pool
from crypt_calculator.rules import (
    CountAtLeast,
    CountEquals,
    RuleSet,
    UniqueAtLeast,
)

BUNDLED = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "crypt_calculator"
    / "examples"
)
TEST_DATA = Path(__file__).resolve().parent / "data"


def test_pool_roundtrip(tmp_path: Path):
    pool = Pool(names=["A", "B", "C", "D"])
    out = tmp_path / "p.yaml"
    save_pool(pool, out)
    loaded = load_pool(out)
    assert loaded.names == pool.names


def test_pool_with_counts_roundtrip(tmp_path: Path):
    pool = Pool(names=["A", "B", "C", "D"])
    counts = {"A": 4, "B": 2, "D": 1}  # C omitted intentionally
    out = tmp_path / "p.yaml"
    save_pool(pool, out, counts)
    loaded_pool, loaded_counts = load_pool_with_counts(out)
    assert loaded_pool.names == pool.names
    assert loaded_counts == counts


def test_pool_load_anson_with_counts():
    """The shipped Anson.crypt.yaml carries counts (the user's manual deck)."""
    pool, counts = load_pool_with_counts(BUNDLED / "Anson.crypt.yaml")
    assert set(pool.names) == {
        "Anneke",
        "Anson",
        "Volker, The Puppet Prince",
        "Black Cat",
        "Sarah Brando",
    }
    assert counts == {
        "Anneke": 1,
        "Anson": 5,
        "Volker, The Puppet Prince": 3,
        "Black Cat": 1,
        "Sarah Brando": 2,
    }


def test_pool_legacy_names_format_still_loads(tmp_path: Path):
    """A v1-style file with the legacy ``names:`` array (no counts) still loads."""
    path = tmp_path / "legacy.yaml"
    with open(path, "w") as f:
        yaml.safe_dump({"version": 1, "names": ["Alpha", "Beta", "Gamma"]}, f)
    pool, counts = load_pool_with_counts(path)
    assert pool.names == ["Alpha", "Beta", "Gamma"]
    assert counts == {}


def test_goratrix_crypt_has_counts():
    """The shipped goratrix.crypt.yaml now ships with a default manual deck."""
    pool, counts = load_pool_with_counts(TEST_DATA / "goratrix.crypt.yaml")
    assert pool.names[0] == "Goratrix"
    assert counts.get("Goratrix", 0) > 0


def test_ruleset_roundtrip_v2(tmp_path: Path):
    rules = RuleSet(
        perfect=[[[CountAtLeast("G", 1)], [UniqueAtLeast(3, frozenset({"G"}))]]],
        good=[[[CountAtLeast("G", 1)], [UniqueAtLeast(2, frozenset({"G"}))]]],
        acceptable=[[[CountAtLeast("G", 1)]]],
    )
    pool = Pool(names=["G", "A", "B"])
    out = tmp_path / "r.yaml"
    save_ruleset(rules, out)
    loaded, note = load_ruleset(out, pool)
    assert note is None  # v2 → no migration note
    assert len(loaded.perfect) == 1
    assert len(loaded.good) == 1
    assert len(loaded.acceptable) == 1
    assert loaded.referenced_cards() == {"G"}


def test_load_example_files_v2():
    pool = load_pool(TEST_DATA / "goratrix.crypt.yaml")
    rules, note = load_ruleset(TEST_DATA / "goratrix.rules.yaml", pool)
    assert note is None  # v2 file
    assert rules.referenced_cards() == {"Goratrix"}
    assert len(rules.perfect) == 1
    assert len(rules.good) == 1
    assert len(rules.acceptable) == 1


def test_load_v1_file_drops_unacceptable(tmp_path: Path):
    """A v1 file with explicit unacceptable rules loads with the unacceptable
    list dropped and a migration note returned."""
    v1_yaml = {
        "version": 1,
        "default": "unacceptable",
        "perfect": [
            {
                "clauses": [
                    {"any": [{"type": "count_at_least", "card": "G", "k": 1}]}
                ]
            }
        ],
        "acceptable": [],
        "unacceptable": [
            {
                "clauses": [
                    {"any": [{"type": "count_equals", "card": "G", "k": 0}]}
                ]
            }
        ],
    }
    path = tmp_path / "v1.yaml"
    with open(path, "w") as f:
        yaml.safe_dump(v1_yaml, f)
    pool = Pool(names=["G", "A"])
    rules, note = load_ruleset(path, pool)
    assert note is not None
    assert "v1" in note.lower() or "unacceptable" in note.lower()
    assert len(rules.perfect) == 1
    assert len(rules.good) == 0
    assert len(rules.acceptable) == 0


def test_load_ruleset_validates_against_pool(tmp_path: Path):
    pool = Pool(names=["A", "B"])
    rules = RuleSet(perfect=[[[CountAtLeast("UNKNOWN", 1)]]])
    out = tmp_path / "_tmp.yaml"
    save_ruleset(rules, out)
    with pytest.raises(ValueError, match="UNKNOWN"):
        load_ruleset(out, pool)
