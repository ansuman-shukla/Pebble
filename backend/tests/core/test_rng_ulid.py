import pytest

from app.core.rng import Rng
from app.lib.ulid import UlidFactory, encode_ulid, ulid_milliseconds


def test_splitmix_matches_the_reference_sequence() -> None:
    # reference values of SplitMix64 seeded with 0 (Vigna's splitmix64.c)
    rng = Rng(0)
    assert [rng.next_u64() for _ in range(3)] == [
        0xE220A8397B1DCDAF,
        0x6E789E6AA1B965F4,
        0x06C45D188009454F,
    ]


def test_subsystem_streams_are_reproducible_and_independent() -> None:
    first = Rng.for_subsystem(7, "ecology")
    again = Rng.for_subsystem(7, "ecology")
    other = Rng.for_subsystem(7, "actions")
    other_seed = Rng.for_subsystem(8, "ecology")
    values = [first.next_u64() for _ in range(5)]
    assert values == [again.next_u64() for _ in range(5)]
    assert values != [other.next_u64() for _ in range(5)]
    assert values != [other_seed.next_u64() for _ in range(5)]


def test_randint_covers_the_whole_inclusive_range_only() -> None:
    rng = Rng(42)
    draws = {rng.randint(3, 6) for _ in range(400)}
    assert draws == {3, 4, 5, 6}
    floats = [rng.random() for _ in range(400)]
    assert all(0.0 <= value < 1.0 for value in floats)
    assert max(floats) > 0.9 and min(floats) < 0.1
    with pytest.raises(ValueError):
        rng.randint(2, 1)


def test_state_restores_the_stream() -> None:
    rng = Rng(5)
    rng.next_u64()
    resumed = Rng(rng.state)
    assert [rng.randint(0, 1000) for _ in range(10)] == [resumed.randint(0, 1000) for _ in range(10)]


def test_ulid_encoding_round_trips_time_and_sorts_by_time() -> None:
    ulid = encode_ulid(1_700_000_000_123, 12345)
    assert len(ulid) == 26
    assert ulid_milliseconds(ulid) == 1_700_000_000_123
    assert encode_ulid(1, 0) < encode_ulid(2, 0) < encode_ulid(2, 1)
    assert encode_ulid(0, 0) == "0" * 26


def test_ulid_factory_is_monotonic_within_a_millisecond() -> None:
    times = iter([100, 100, 100, 99, 101])
    factory = UlidFactory(clock_ms=lambda: next(times), entropy=lambda: 7)
    ids = [factory.new() for _ in range(5)]
    assert ids == sorted(ids)
    assert len(set(ids)) == 5
    assert [ulid_milliseconds(value) for value in ids] == [100, 100, 100, 100, 101]
