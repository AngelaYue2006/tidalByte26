"""T3-T5: budget, free-window and insurance filters."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from app.ranking import (
    NO_ELIGIBLE_OFFER,
    fits_windows,
    hard_rules,
    money,
    no_eligible_offer,
    slot_label,
)

TZ = UTC
THU = datetime(2026, 11, 26, tzinfo=TZ)
TUE = datetime(2026, 11, 24, tzinfo=TZ)
FRI = datetime(2026, 11, 27, tzinfo=TZ)
MON = datetime(2026, 11, 30, tzinfo=TZ)


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
    insured: bool = True
    distance_mi: float = 1.0
    drive_min: float = 5


WINDOWS = [Window(TUE.replace(hour=13), TUE.replace(hour=17)), Window(THU.replace(hour=8), THU.replace(hour=12))]


def offer(call_id, clinic, price, start, insured=True, minutes=60):
    return Offer(call_id, clinic, price, start, start + timedelta(minutes=minutes), insured)


BRIGHT = offer("a", "Bright Smile Dental", 95, THU.replace(hour=9, minute=30))
SMILE = offer("b", "Smile Co.", 120, FRI.replace(hour=16))
OAK = offer("c", "Oak Dental", 140, MON.replace(hour=10))


def test_standard_run_keeps_only_bright_smile():
    result = hard_rules([BRIGHT, SMILE, OAK], WINDOWS, budget_max=150, carrier="Delta Dental")
    assert [o.call_id for o in result.eligible] == ["a"]
    assert result.ok
    assert result.reasons_for("b") == ("OUTSIDE_WINDOWS",)
    assert result.reasons_for("c") == ("OUTSIDE_WINDOWS",)
    assert result.reasons_for("a") == ()


def test_t3_all_over_budget_fails_honestly():
    result = hard_rules([BRIGHT, SMILE, OAK], WINDOWS, budget_max=50, carrier="Delta Dental")
    assert not result.ok
    assert all("OVER_BUDGET" in r.reasons for r in result.rejected)
    failure = no_eligible_offer(result)
    assert failure["code"] == NO_ELIGIBLE_OFFER
    assert failure["rejected"] == ["a", "b", "c"]
    for clinic, price in (("Bright Smile Dental", "$95"), ("Smile Co.", "$120"), ("Oak Dental", "$140")):
        assert clinic in failure["message"]
        assert price in failure["message"]
    assert "nothing was booked" in failure["message"]
    assert "$50 budget" in failure["message"]


def test_t4_offer_outside_free_windows_is_removed_before_ranking():
    result = hard_rules([BRIGHT, SMILE], WINDOWS, budget_max=150, carrier="Delta Dental")
    assert [o.call_id for o in result.eligible] == ["a"]
    (rej,) = result.rejected
    assert rej.call_id == "b"
    assert rej.reasons == ("OUTSIDE_WINDOWS",)
    assert "Fri 4:00" in rej.detail


def test_t5_clinic_not_taking_the_insurance_is_removed():
    uninsured = offer("d", "Cash Only Dental", 80, THU.replace(hour=10), insured=False)
    result = hard_rules([BRIGHT, uninsured], WINDOWS, budget_max=150, carrier="Delta Dental")
    assert [o.call_id for o in result.eligible] == ["a"]
    assert result.reasons_for("d") == ("NOT_INSURED",)
    assert "does not take Delta Dental" in result.rejected[0].detail


def test_every_broken_rule_is_recorded_not_just_the_first():
    bad = offer("e", "Far Dental", 200, MON.replace(hour=9), insured=False)
    result = hard_rules([bad], WINDOWS, budget_max=150, carrier="Delta Dental")
    assert result.reasons_for("e") == ("OVER_BUDGET", "OUTSIDE_WINDOWS", "NOT_INSURED")


def test_no_budget_or_no_carrier_means_that_rule_does_not_apply():
    uninsured = offer("d", "Cash Only Dental", 999, THU.replace(hour=10), insured=False)
    result = hard_rules([uninsured], WINDOWS, budget_max=None, carrier=None)
    assert result.ok


def test_boundaries_are_inclusive_and_price_equal_to_budget_passes():
    edge = offer("f", "Edge Dental", 150, THU.replace(hour=8), minutes=240)  # 8:00-12:00 exactly
    assert fits_windows(edge, WINDOWS)
    result = hard_rules([edge], WINDOWS, budget_max=150, carrier="Delta Dental")
    assert result.ok


def test_slot_spilling_past_the_window_end_does_not_fit():
    spill = offer("g", "Late Dental", 90, THU.replace(hour=11, minute=30), minutes=60)  # ends 12:30
    assert not fits_windows(spill, WINDOWS)


def test_no_windows_means_nothing_fits():
    assert not fits_windows(BRIGHT, [])


def test_no_eligible_offer_refuses_when_something_survived():
    with pytest.raises(ValueError):
        no_eligible_offer(hard_rules([BRIGHT], WINDOWS, 150, "Delta Dental"))


def test_no_eligible_offer_with_no_calls_at_all_is_still_honest():
    failure = no_eligible_offer(hard_rules([], WINDOWS, 150, "Delta Dental"))
    assert failure["code"] == NO_ELIGIBLE_OFFER
    assert "nothing was booked" in failure["message"]


def test_labels_match_the_prototype_style():
    assert money(95) == "$95"
    assert money(95.5) == "$95.50"
    assert money(1200) == "$1,200"
    assert slot_label(THU.replace(hour=9, minute=30)) == "Thu 9:30"
    assert slot_label(FRI.replace(hour=16)) == "Fri 4:00"
    assert slot_label(MON.replace(hour=0, minute=5)) == "Mon 12:05"
