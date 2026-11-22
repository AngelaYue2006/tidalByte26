"""#107: the request chips label free windows honestly: one part of a day, a multi-day span, or the whole requested range."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.texts import chips, window_chip

TZ = ZoneInfo("America/Chicago")


def at(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, tzinfo=TZ)


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


RANGE = (at(23, 0), at(29, 23, 59, 59))  # "next week" as Nano resolves it on Sat Nov 21


def test_fixture_windows_keep_the_part_of_day_labels():
    windows = [Window(at(24, 13), at(24, 17)), Window(at(26, 8), at(26, 12))]
    assert chips("dental cleaning", 150, "Delta Dental", windows, RANGE) == ["Dental cleaning", "Max $150", "Delta Dental", "Free: Tue pm, Thu am", "!Processed on device"]
    assert chips("dental cleaning", 150, "Delta Dental", windows) == ["Dental cleaning", "Max $150", "Delta Dental", "Free: Tue pm, Thu am", "!Processed on device"]


def test_live_freebusy_spans_read_as_day_ranges():
    """Task ea248255: the week free except Tue 9:30-10:00 came back as two spans and read "Mon am, Tue am"."""
    windows = [Window(at(23, 0), at(24, 9, 30)), Window(at(24, 10), at(29, 23, 59, 59))]
    assert chips("dental cleaning", 150, "Delta Dental", windows, RANGE)[3] == "Free: Mon–Tue, Tue–Sun"


def test_one_window_covering_the_requested_range_reads_all_week():
    assert window_chip(at(23, 0), at(29, 23, 59, 59), RANGE) == "all week"
    assert window_chip(at(22, 0), at(30, 0), RANGE) == "all week", "wider than the range still covers it"
    assert window_chip(at(23, 0), at(29, 23, 59, 59), None) == "Mon–Sun", "without the range it is a plain span"
    assert window_chip(at(23, 0), at(28, 23, 59, 59), RANGE) == "Mon–Sat", "a day short of the range is not all week"


def test_window_ending_at_midnight_is_one_day():
    assert window_chip(at(26, 8), at(27, 0)) == "Thu am"
    assert window_chip(at(26, 13), at(27, 0)) == "Thu pm"
    assert window_chip(at(26, 13), at(27, 0, 0, 1)) == "Thu–Fri"
