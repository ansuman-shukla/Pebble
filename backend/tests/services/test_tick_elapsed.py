"""How far into the current tick the world is (a page opened mid-tick draws walkers that far along, D100)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.entities import tick_elapsed

WRITTEN = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def _later(seconds: float) -> datetime:
    return WRITTEN + timedelta(seconds=seconds)


def test_game_seconds_pass_at_the_clock_s_speed_from_when_the_tick_was_written() -> None:
    assert tick_elapsed(0.0, WRITTEN, 1.0, False, _later(25)) == pytest.approx(25.0)
    assert tick_elapsed(0.0, WRITTEN, 10.0, False, _later(2.5)) == pytest.approx(25.0)
    assert tick_elapsed(12.0, WRITTEN, 10.0, False, _later(1)) == pytest.approx(22.0)  # 12 counted, then 10 more


def test_a_paused_clock_keeps_what_was_counted() -> None:
    assert tick_elapsed(12.0, WRITTEN, 10.0, True, _later(300)) == 12.0


def test_it_never_leaves_the_tick() -> None:
    assert tick_elapsed(0.0, WRITTEN, 600.0, False, _later(1)) == 60.0  # the next tick is late: the end of this one
    assert tick_elapsed(0.0, WRITTEN, 1.0, False, _later(-0.5)) == 0.0  # clocks a little apart
