from uuid import uuid4

import pytest

from services import plans_service
from services.plans_service import (
    _borda_scores,
    _determine_consensus,
    _first_choice_counts,
    _normalize_refinement_descriptors,
    _parse_rankings,
    _top_n_sets,
)


# --- Base Sanity ---
@pytest.mark.asyncio
async def test_plans_service_initialization():
    assert plans_service is not None


# --- Parsing Rankings & Types ---
def test_parse_rankings_valid_json_string():
    assert _parse_rankings('["uuid-1", "uuid-2"]') == ["uuid-1", "uuid-2"]


def test_parse_rankings_malformed_json_returns_empty():
    assert _parse_rankings('["uuid-1", "uuid-2"') == []


def test_parse_rankings_handles_none_and_empty():
    assert _parse_rankings(None) == []
    assert _parse_rankings("[]") == []


def test_parse_rankings_handles_integer_injection():
    assert _parse_rankings([1, 2, 3]) == ["1", "2", "3"]


def test_parse_rankings_filters_nulls_in_list():
    assert _parse_rankings('["uuid", null]') == ["uuid"]


# --- Borda Math & Voting Loops ---
def test_borda_scores_standard_5_plans():
    votes = [{"rankings": ["A", "B", "C", "D", "E"]}]
    scores = _borda_scores(votes, num_plans=5)
    assert scores == {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}


def test_borda_scores_partial_votes():
    votes = [{"rankings": ["A", "B"]}]
    scores = _borda_scores(votes, num_plans=5)
    assert scores == {"A": 5, "B": 4}


def test_borda_scores_empty_votes():
    assert _borda_scores([]) == {}


def test_borda_scores_all_vote_same():
    votes = [{"rankings": ["A", "B"]}, {"rankings": ["A", "B"]}]
    scores = _borda_scores(votes, num_plans=5)
    assert scores == {"A": 10, "B": 8}


def test_borda_scores_same_rankings_injection():
    # Exploiting the Borda scoring logic flaw found
    votes = [{"rankings": ["A", "A", "A", "A", "A"]}]
    scores = _borda_scores(votes)
    # Testing that it acts predictably based on current service code
    assert scores["A"] == 15


# --- Consensus Strategies ---
def test_consensus_strategy1_true_majority():
    votes = [
        {"rankings": ["A", "B", "C"]},
        {"rankings": ["A", "D", "E"]},
        {"rankings": ["B", "C", "A"]},
    ]
    consensus, winner, _ = _determine_consensus(votes, 3)
    assert consensus is True
    assert winner == "A"


def test_consensus_strategy2_borda_lead_with_overlap():
    votes = [
        {"rankings": ["A", "B", "C"]},
        {"rankings": ["C", "A", "B"]},
        {"rankings": ["D", "A", "B"]},
        {"rankings": ["E", "A", "B"]},
    ]
    consensus, winner, _ = _determine_consensus(votes, 4)
    assert consensus is True
    assert winner == "A"


def test_consensus_borda_lead_fails_without_overlap():
    votes = [
        {"rankings": ["B", "A", "C"]},
        {"rankings": ["A", "C", "B"]},
        {"rankings": ["A", "D", "B"]},
        {"rankings": ["E", "B", "C", "A"]},
    ]
    consensus, winner, _ = _determine_consensus(votes, 4)
    assert consensus is False


def test_consensus_strategy3_small_group_tiebreak():
    votes = [{"rankings": ["A", "B", "C"]}, {"rankings": ["B", "A", "C"]}]
    consensus, winner, _ = _determine_consensus(votes, 2)
    assert consensus is True
    assert winner in ["A", "B"]


def test_consensus_empty_group():
    consensus, winner, _ = _determine_consensus([], 0)
    assert consensus is False


def test_consensus_only_one_vote_cast_never_determines_majority_if_members_large():
    votes = [{"rankings": ["A"]}]
    consensus, _, _ = _determine_consensus(votes, 10)
    assert consensus is False


# --- Additional Resiliency Scenarios ---
def test_first_choice_counts_empty_rankings():
    # Ensure voter leaving everything blank doesn't crash
    votes = [{"rankings": "[]"}]
    counts = _first_choice_counts(votes)
    assert counts == {}


def test_top_n_sets_missing_data():
    votes = [{"rankings": []}, {"rankings": ["A"]}]
    results = _top_n_sets(votes, n=3)
    assert results == [set(), {"A"}]


def test_normalize_refinement_descriptors_garbage():
    res = _normalize_refinement_descriptors(
        ["completely_unknown_descriptor", None, "", "indoor"]
    )
    assert res == ["indoor"]


def test_cost_from_price_level_parser():
    from agents.planning import _cost_from_price_level

    # Ensuring Google Maps price levels translate
    assert _cost_from_price_level("PRICE_LEVEL_MODERATE") == "$20-40 per person"
    assert _cost_from_price_level(2) == "$20-40 per person"
    assert _cost_from_price_level("unparsable") == "$20-40 per person"  # default
    assert _cost_from_price_level(-5) == "$0-10 per person"
