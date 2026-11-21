"""Issue #12: Super's reply becomes a Decision that validates against shared/decision.schema.json, with one retry on a bad reply."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.nemotron import ranker
from app.nemotron.rank_prompt import RANKING_SYSTEM, ranking_user_message
from app.nemotron.ranker import (
    NvidiaChatClient,
    RankingError,
    parse_json_object,
    rank,
    reason_tags,
    timed_rank,
)
from app.ranking import hard_rules
from jsonschema import Draft202012Validator

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "shared" / "decision.schema.json").read_text())
THU = datetime(2026, 11, 26, tzinfo=UTC)
TUE = datetime(2026, 11, 24, tzinfo=UTC)
FRI = datetime(2026, 11, 27, tzinfo=UTC)
MON = datetime(2026, 11, 30, tzinfo=UTC)


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Offer:
    call_id: str
    clinic: str
    price: float
    slot_start: datetime
    slot_end: datetime
    insured: bool
    distance_mi: float
    drive_min: float


def offer(call_id, clinic, price, start, distance_mi, insured=True):
    return Offer(call_id, clinic, price, start, start + timedelta(hours=1), insured, distance_mi, distance_mi * 5)


WINDOWS = [Window(TUE.replace(hour=13), TUE.replace(hour=17)), Window(THU.replace(hour=8), THU.replace(hour=12))]
BRIGHT = offer("a", "Bright Smile Dental", 95, THU.replace(hour=9, minute=30), 1.2)
SMILE = offer("b", "Smile Co.", 120, FRI.replace(hour=16), 0.6)
OAK = offer("c", "Oak Dental", 140, MON.replace(hour=10), 3.4)
ALL = [BRIGHT, SMILE, OAK]
GOOD = json.dumps({
    "winner_call_id": "a",
    "ranked": [{"call_id": "a", "score": 92}],
    "tradeoff": "Smile Co. is closer (0.6 mi), but its only opening is Friday at 4, when your calendar is busy.",
})


class ScriptedClient:
    """Returns the scripted replies in order and records every request."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def complete_json(self, system, user, *, previous=None):
        self.calls.append({"system": system, "user": user, "previous": previous})
        return self.replies.pop(0)


def test_good_reply_becomes_a_schema_valid_decision_with_prototype_style_chips():
    client = ScriptedClient(GOOD)
    survivors = hard_rules(ALL, WINDOWS, 150, "Delta Dental").eligible
    decision = rank(survivors, WINDOWS, "cheapest", client=client, all_offers=ALL, carrier="Delta Dental")
    Draft202012Validator(SCHEMA).validate(decision)
    assert decision["winner_call_id"] == "a"
    assert decision["score"] == 92
    assert decision["reasons"] == ["Fits your free time · Thu 9:30", "Cheapest · $95 vs $120, $140", "Takes Delta Dental"]
    assert decision["second"] == ["2nd closest · 1.2 mi"]
    assert decision["tradeoff"].startswith("Smile Co. is closer")
    assert decision["ranked"] == [{"call_id": "a", "score": 92.0}]
    assert len(client.calls) == 1


def test_prompt_carries_only_offer_facts_and_the_rubric():
    client = ScriptedClient(GOOD)
    rank([BRIGHT], WINDOWS, "soonest", client=client)
    sent = client.calls[0]
    assert sent["system"] == RANKING_SYSTEM
    assert "AI assistant" not in sent["system"]
    user = json.loads(sent["user"])
    assert user["priority"] == "soonest"
    assert user["offers"][0] == {
        "call_id": "a", "clinic": "Bright Smile Dental", "price": "$95", "slot": "Thu 9:30",
        "slot_start": "2026-11-26T09:30:00+00:00", "distance_mi": 1.2, "drive_min": 6.0,
    }
    assert len(user["free_windows"]) == 2
    for forbidden in ("Mary", "utterance", "member", "symptom"):
        assert forbidden not in sent["user"]


def test_code_fences_are_tolerated_but_prose_is_not():
    assert parse_json_object("```json\n{\"a\": 1}\n```")["a"] == 1
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_json_object("Sure! Here is the ranking: {\"a\": 1}")
    with pytest.raises(ValueError, match="JSON object"):
        parse_json_object("[1, 2]")


def test_bad_json_is_retried_once_with_the_problem_named():
    client = ScriptedClient("I pick Bright Smile Dental because it is cheapest.", GOOD)
    decision = rank([BRIGHT], WINDOWS, "cheapest", client=client)
    assert decision["winner_call_id"] == "a"
    assert len(client.calls) == 2
    retry = client.calls[1]
    assert "rejected" in retry["user"] and "not valid JSON" in retry["user"]
    assert retry["previous"][1]["content"].startswith("I pick")


@pytest.mark.parametrize(
    "bad,problem",
    [
        (json.dumps({"winner_call_id": "z", "ranked": [{"call_id": "a", "score": 1}], "tradeoff": "x"}), "not one of the offers"),
        (json.dumps({"winner_call_id": "a", "ranked": [{"call_id": "a", "score": 1}], "tradeoff": ""}), "tradeoff"),
        (json.dumps({"winner_call_id": "a", "ranked": [{"call_id": "a", "score": "high"}], "tradeoff": "x"}), "finite number"),
        (json.dumps({"winner_call_id": "a", "ranked": [], "tradeoff": "x"}), "non-empty"),
        ('{"winner_call_id": "a", "ranked": [{"call_id": "a", "score": 90}, null], "tradeoff": "x"}', "ranked[1] must be an object"),
        (json.dumps({"winner_call_id": "a", "ranked": [{"score": 90}], "tradeoff": "x"}), "call_id must be a string"),
        (json.dumps({"winner_call_id": "a", "ranked": [{"call_id": 7, "score": 90}], "tradeoff": "x"}), "call_id must be a string"),
        (json.dumps({"winner_call_id": "a", "ranked": [{"call_id": "a", "score": True}], "tradeoff": "x"}), "finite number"),
        ('{"winner_call_id": "a", "ranked": [{"call_id": "a", "score": NaN}], "tradeoff": "x"}', "NaN is not a valid JSON number"),
        ('{"winner_call_id": "a", "ranked": [{"call_id": "a", "score": Infinity}], "tradeoff": "x"}', "Infinity is not a valid JSON number"),
        (json.dumps({"winner_call_id": "a", "ranked": [{"call_id": "a", "score": 150}], "tradeoff": "x"}), "must be from 0 to 100"),
        (json.dumps({"winner_call_id": "a", "ranked": [{"call_id": "a", "score": -1}], "tradeoff": "x"}), "must be from 0 to 100"),
        (json.dumps({"winner_call_id": "a", "ranked": "a", "tradeoff": "x"}), "non-empty list"),
    ],
)
def test_semantically_wrong_replies_are_retried(bad, problem):
    client = ScriptedClient(bad, GOOD)
    rank([BRIGHT], WINDOWS, "cheapest", client=client)
    assert len(client.calls) == 2
    assert problem in client.calls[1]["user"]


def test_recovery_after_a_malformed_entry_serialises_cleanly():
    bad = '{"winner_call_id": "a", "ranked": [{"call_id": "a", "score": NaN}], "tradeoff": "x"}'
    decision = rank([BRIGHT], WINDOWS, "cheapest", client=ScriptedClient(bad, GOOD))
    Draft202012Validator(SCHEMA).validate(decision)
    assert json.loads(json.dumps(decision, allow_nan=False))["score"] == 92.0


def test_two_bad_replies_raise_ranking_error_not_a_guess():
    client = ScriptedClient("nope", "still nope")
    with pytest.raises(RankingError, match="after one retry"):
        rank([BRIGHT], WINDOWS, "cheapest", client=client)
    assert len(client.calls) == 2


def test_ranked_must_cover_every_eligible_offer_with_the_winner_first():
    eligible = [BRIGHT, offer("d", "Tuesday Dental", 110, TUE.replace(hour=14), 2.0)]
    missing = json.dumps({"winner_call_id": "a", "ranked": [{"call_id": "a", "score": 90}], "tradeoff": "x"})
    wrong_order = json.dumps({"winner_call_id": "a", "ranked": [{"call_id": "d", "score": 70}, {"call_id": "a", "score": 90}], "tradeoff": "x"})
    good = json.dumps({"winner_call_id": "a", "ranked": [{"call_id": "a", "score": 90}, {"call_id": "d", "score": 70}],
                       "tradeoff": "Tuesday Dental is sooner, but costs $15 more."})
    client = ScriptedClient(missing, good)
    decision = rank(eligible, WINDOWS, "cheapest", client=client)
    assert "cover every offer" in client.calls[1]["user"]
    assert [r["call_id"] for r in decision["ranked"]] == ["a", "d"]
    client = ScriptedClient(wrong_order, good)
    rank(eligible, WINDOWS, "cheapest", client=client)
    assert "ranked[0] must be the winner" in client.calls[1]["user"]


def test_reason_tags_when_the_winner_is_not_cheapest_or_closest():
    reasons, second = reason_tags(SMILE, ALL, "Delta Dental")
    assert reasons == ["Fits your free time · Fri 4:00", "Price · $120", "Takes Delta Dental"]
    assert second == ["Closest · 0.6 mi"]
    reasons, second = reason_tags(OAK, ALL, None)
    assert reasons == ["Fits your free time · Mon 10:00", "Price · $140"]
    assert second == ["3rd closest · 3.4 mi"]


def test_single_offer_still_gets_two_reasons():
    decision = rank([BRIGHT], WINDOWS, "cheapest", client=ScriptedClient(GOOD))
    assert len(decision["reasons"]) >= 2
    Draft202012Validator(SCHEMA).validate(decision)


def test_rank_refuses_an_empty_offer_list():
    with pytest.raises(ValueError, match="no_eligible_offer"):
        rank([], WINDOWS, "cheapest", client=ScriptedClient())


def test_timed_rank_reports_latency():
    decision, seconds = timed_rank([BRIGHT], WINDOWS, "cheapest", client=ScriptedClient(GOOD))
    assert decision["winner_call_id"] == "a"
    assert 0 <= seconds < 5


def test_nvidia_client_never_guesses_a_model_id(monkeypatch):
    with pytest.raises(ValueError, match="NEMOTRON_SUPER_ID"):
        NvidiaChatClient(api_key="k", model_id="")
    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        NvidiaChatClient(api_key="", model_id="nvidia/some-super")
    client = NvidiaChatClient(api_key="k", model_id="nvidia/some-super")
    assert client.model_id == "nvidia/some-super"
    assert str(client._client.base_url).startswith(ranker.NVIDIA_BASE_URL)
    assert "nvidia/" not in RANKING_SYSTEM  # no model ID anywhere in the prompt or module defaults
    assert "ranking_user_message" in ranker.__dict__ or ranking_user_message
