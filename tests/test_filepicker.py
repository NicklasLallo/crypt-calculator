from __future__ import annotations

from crypt_calculator.screens.filepicker import (
    _highlight_matches,
    fuzzy_match,
    fuzzy_score,
)


def test_empty_query_matches_everything():
    assert fuzzy_score("", "anything") == 0
    assert fuzzy_score("", "") == 0


def test_subsequence_match():
    assert fuzzy_score("ans", "anson.crypt.yaml") is not None
    assert fuzzy_score("crypt", "anson.crypt.yaml") is not None
    # non-contiguous subsequence
    assert fuzzy_score("aca", "anson.crypt.yaml") is not None


def test_no_match_returns_none():
    assert fuzzy_score("xyz", "anson.crypt.yaml") is None
    # order matters — 'y' appears once in "yaml" with no 'a' after, so "yaa" fails
    assert fuzzy_score("yaa", "anson.crypt.yaml") is None


def test_case_insensitive():
    assert fuzzy_score("ANSON", "anson.crypt.yaml") is not None
    assert fuzzy_score("anson", "ANSON.crypt.yaml") is not None


def test_consecutive_beats_scattered():
    # "anson" matched consecutively in "anson..." should beat scattered match
    score_consec = fuzzy_score("ans", "anson.crypt.yaml")
    score_scattered = fuzzy_score("ans", "anaspirans.yaml")  # also matches
    assert score_consec is not None and score_scattered is not None
    assert score_consec > score_scattered


def test_word_boundary_bonus():
    # 'c' at position 6 in "anson.crypt.yaml" is a word boundary (after '.')
    # while 'c' inside another word should score lower
    boundary = fuzzy_score("c", "anson.crypt.yaml")
    interior = fuzzy_score("c", "abcdefgh.yaml")
    assert boundary is not None and interior is not None
    assert boundary > interior


def test_shorter_candidate_preferred():
    score_short = fuzzy_score("a", "a.yaml")
    score_long = fuzzy_score("a", "alphabet.yaml")
    assert score_short > score_long


def test_fuzzy_match_returns_positions():
    m = fuzzy_match("ne", "Nehemiah.rules.yaml")
    assert m is not None
    _, positions = m
    assert positions == [0, 1]  # N, e at start


def test_fuzzy_match_subsequence_positions():
    # "ne" against "Anson.rules.yaml": n at 1 ('n' of Anson), e at 9 ('e' of rules)
    m = fuzzy_match("ne", "Anson.rules.yaml")
    assert m is not None
    _, positions = m
    assert positions == [1, 9]


def test_highlight_matches_consecutive():
    out = _highlight_matches("Nehemiah.rules.yaml", [0, 1])
    assert out == "[yellow]Ne[/yellow]hemiah.rules.yaml"


def test_highlight_matches_split():
    out = _highlight_matches("Anson.rules.yaml", [1, 9])
    assert out == "A[yellow]n[/yellow]son.rul[yellow]e[/yellow]s.yaml"


def test_highlight_matches_no_positions():
    assert _highlight_matches("plain.yaml", []) == "plain.yaml"
