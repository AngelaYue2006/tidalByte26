"""Deterministic intake backstops: spelled-out dollars, carrier names, ride cues, identifier detection, time-phrase resolution."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from app.nemotron import intake_backstop as b

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=ZoneInfo("America/Chicago"))


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("two hundred", 200), ("one fifty", 150), ("a hundred and twenty-five", 125), ("forty", 40),
        ("hundred", 100), ("ninety nine", 99), ("three thousand", 3000), ("twelve", 12), ("banana", None),
    ],
)
def test_words_to_number(text, value):
    assert b.words_to_number(text) == value


@pytest.mark.parametrize(
    ("utterance", "budget"),
    [
        ("under $150. I have Delta Dental.", 150),
        ("no more than forty dollars, and I don't have a car.", 40),
        ("keep it under two hundred.", 200),
        ("Budget around a hundred.", 100),
        ("I'd rather not spend more than fifty.", 50),
        ("No insurance, I'll pay cash, two hundred tops.", 200),
        ("under eighty bucks, I have VSP.", 80),
        ("max $90, and I can't drive", 90),
        ("under one fifty.", 150),
        ("under a hundred and twenty-five dollars", 125),
        ("Price doesn't matter.", None),
        ("I take 2 pills a day, book me a cleaning", None),
    ],
)
def test_extract_budget(utterance, budget):
    assert b.extract_budget(utterance) == budget


@pytest.mark.parametrize(
    ("utterance", "carrier"),
    [
        ("I have Delta Dental", "Delta Dental"), ("$95 with Delta", "Delta Dental"), ("I'm on Medicare", "Medicare"),
        ("Blue Cross, max $90", "Blue Cross Blue Shield"), ("Cigna dental", "Cigna"), ("I have UnitedHealthcare", "UnitedHealthcare"),
        ("No insurance, I'll pay cash", None), ("book me a flu shot tomorrow", None),
    ],
)
def test_extract_carrier(utterance, carrier):
    assert b.extract_carrier(utterance) == carrier


@pytest.mark.parametrize(
    ("utterance", "ride"),
    [
        ("so I'll need a ride.", True), ("I don't have a car.", True), ("I can't drive while I'm on it.", True),
        ("I'll need someone to drive me.", True), ("a ride because of my walker", True), ("I can't take the bus anymore.", True),
        ("I can drive myself.", False), ("I can get there on my own.", False), ("Price doesn't matter.", None),
    ],
)
def test_extract_needs_ride(utterance, ride):
    assert b.extract_needs_ride(utterance) is ride


@pytest.mark.parametrize(
    ("utterance", "kinds"),
    [
        ("My Delta Dental member ID is DEMO-0000-0000-0001.", ["member_id"]),
        ("her number is 555-555-0101.", ["contact_phone"]),
        ("date of birth March 14, 1948.", ["date_of_birth"]),
        ("born 3/14/48, member number DEMO-0000-0000-0001", ["member_id", "date_of_birth"]),
        ("I live at 100 Example Street, Chicago 60601.", ["address"]),
        ("I live on Example Street", ["address"]),
        ("I need a cleaning this week under $150", []),
    ],
)
def test_detect_identifiers(utterance, kinds):
    assert b.detect_identifiers(utterance) == kinds


def test_identifier_values_are_the_literal_strings():
    values = b.identifier_values("born 3/14/48, ID DEMO-0000-0000-0001, call 555-555-0101, I live at 100 Example Street.")
    assert {"3/14/48", "DEMO-0000-0000-0001", "555-555-0101", "100 Example Street"} <= set(values)
    assert not any(v.lower().startswith("live") for v in values)


@pytest.mark.parametrize(
    ("phrase", "start", "end"),
    [
        ("this week", "2026-11-23T00:00:00-06:00", "2026-11-29T23:59:59-06:00"),
        ("next week", "2026-11-30T00:00:00-06:00", "2026-12-06T23:59:59-06:00"),
        ("tomorrow", "2026-11-24T00:00:00-06:00", "2026-11-24T23:59:59-06:00"),
        ("this month", "2026-11-23T00:00:00-06:00", "2026-11-30T23:59:59-06:00"),
        ("next month", "2026-12-01T00:00:00-06:00", "2026-12-31T23:59:59-06:00"),
        ("within two weeks", "2026-11-23T00:00:00-06:00", "2026-12-06T23:59:59-06:00"),
        ("any", "2026-11-23T00:00:00-06:00", "2026-12-22T23:59:59-06:00"),
        ("sometime soonish", "2026-11-23T00:00:00-06:00", "2026-12-06T23:59:59-06:00"),
    ],
)
def test_resolve_time_range(phrase, start, end):
    assert b.resolve_time_range(phrase, NOW) == (start, end)


@pytest.mark.parametrize(
    ("utterance", "phrase"),
    [
        ("I need a cleaning this week", "this week"), ("sometime next week?", "next week"), ("a flu shot tomorrow, no more than forty", "tomorrow"),
        ("within the next two weeks", "within two weeks"), ("in the next two weeks", "within two weeks"),
        ("any time next month", "next month"), ("this month", "this month"), ("I need new glasses", None),
    ],
)
def test_extract_time_phrase(utterance, phrase):
    assert b.extract_time_phrase(utterance) == phrase
