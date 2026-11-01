"""Each ambition check's predicate and progress (10-world-v1 §3.1, §7) on a hand-built replayed world and events."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, get_args

from app.observability.replay import ReplayCitizen, ReplayState, from_snapshot
from app.services.ambitions import CHECKS, Facts, Record, ambition_progress, cast_ambitions, clause_progress
from app.sim.citizens import CITIZENS, Ambition, AmbitionCheck, AmbitionClause, load_citizens
from app.sim.clock import DAY_MINUTES
from app.sim.simulation import Simulation
from app.sim.snapshot import take_snapshot
from app.sim.society import Member
from app.sim.state import Region

Told = tuple[int, str, str | None, Mapping[str, Any]]  # an event: tick, type, actor, payload
DAY = DAY_MINUTES
NOW = 10 * DAY  # day 11, the fourth day of the second week


def person(citizen_id: str, region: Region = "town", home: str | None = None, **fields: Any) -> ReplayCitizen:
    return ReplayCitizen(
        id=citizen_id,
        name=citizen_id.title(),
        look="",
        appearance="",
        age=30,
        group="young_adult",
        home=home,
        position=(0.0, 0.0, 1.0),
        height_m=0.0,
        cell=0,
        region=region,
        **({"body": (10.0, 10.0, 90.0, 100.0)} | fields),
    )


def facts(
    citizens: list[ReplayCitizen],
    events: Sequence[Told] = (),
    stores: dict[str, dict[str, int]] | None = None,
    tick: int = NOW,
) -> Facts:
    state = ReplayState(tick=tick, citizens={c.id: c for c in citizens}, ground={}, stores=stores or {})
    records = [Record(seq, at, kind, actor, data) for seq, (at, kind, actor, data) in enumerate(events, 1)]
    return Facts(tick=tick, state=state, events=records)


def check(given: Facts, me: str, name: AmbitionCheck, **args: str | int) -> tuple[bool, int]:
    progress = clause_progress(given, given.state.citizens[me], AmbitionClause(check=name, args=args))
    return progress.met, progress.progress


ME = person("me", home="house-1")


def test_every_check_of_the_cast_has_a_predicate() -> None:
    assert set(CHECKS) == set(get_args(AmbitionCheck))


def test_store_holds_and_at_the_week_s_end() -> None:
    world = facts([ME], stores={"store-2": {"rice": 450}})
    assert check(world, "me", "store_holds", store="store-2", item="rice", count=600) == (False, 75)
    assert check(world, "me", "store_holds", store="store-2", item="rice", count=450) == (True, 100)
    assert check(world, "me", "store_holds", store="store-2", item="wood", count=10) == (False, 0)
    week_end = facts([ME], stores={"store-2": {"rice": 600}}, tick=6 * DAY + 600)  # day 7: the week's last
    mid_week = facts([ME], stores={"store-2": {"rice": 600}}, tick=5 * DAY + 600)
    args: dict[str, str | int] = {"store": "store-2", "item": "rice", "count": 600, "at": "week end"}
    assert check(week_end, "me", "store_holds", **args) == (True, 100)
    assert check(mid_week, "me", "store_holds", **args) == (False, 99)  # full, but not yet the week's end


def test_standing_at_least_of_themselves_or_someone_else() -> None:
    ama = person("ama", "band_a", standing={"band_a": 60, "town": 10})
    me = person("me", standing={"town": 30})
    world = facts([me, ama])
    assert check(world, "me", "standing_at_least", group="town", value=30) == (True, 100)
    assert check(world, "me", "standing_at_least", group="town", value=30, who="ama") == (False, 85)  # 110 / 130
    assert check(world, "me", "standing_at_least", group="band_a", value=30, who="ama") == (True, 100)


def _theft(owner: str, witnesses: list[str]) -> dict[str, Any]:
    return {"owner": owner, "store": "x", "item": "rice", "count": 1, "witnesses": witnesses}


def test_deeds_judged_counts_witnessed_deeds_against_the_group_in_the_window() -> None:
    thief, farmer, wolfboy = person("thief", "band_b"), person("farmer", home="farmhouse-1"), person("wb", "band_a")
    events = [
        (NOW - 20 * DAY, "stole", "thief", _theft("farmhouse-1", ["farmer"])),  # 1: too old
        (NOW - 3 * DAY, "stole", "thief", _theft("farmhouse-1", ["farmer"])),  # 2: judged below
        (NOW - 2 * DAY, "stole", "thief", _theft("farmhouse-1", ["farmer"])),  # 3: not judged
        (NOW - 2 * DAY, "stole", "thief", _theft("farmhouse-1", [])),  # 4: nobody saw
        (NOW - 2 * DAY, "stole", "thief", _theft("band_a", ["wb"])),  # 5: against band A
        (NOW - DAY, "judged", "kenji", {"person": "thief", "sentence": "fine", "deeds": [2]}),
    ]
    world = facts([ME, thief, farmer, wolfboy], events)
    assert check(world, "me", "deeds_judged", group="town", days=14) == (False, 50)
    assert check(world, "me", "deeds_judged", group="band_b", days=14) == (True, 100)  # none against them
    judged_all = [*events, (NOW, "judged", "kenji", {"person": "thief", "sentence": "fine", "deeds": [3]})]
    assert check(facts([ME, thief, farmer, wolfboy], judged_all), "me", "deeds_judged", group="town", days=14) == (
        True,
        100,
    )


def test_violence_is_a_witnessed_deed_against_the_victim_s_group() -> None:
    brute, victim = person("brute", "band_b"), person("victim", "band_a")
    hit = (NOW - DAY, "injured", "victim", {"amount": 10, "cause": "violence", "attacker": "brute"})
    bite = (NOW - DAY, "injured", "victim", {"amount": 10, "cause": "animal attack", "attacker": "wolf:1"})
    fall = (NOW, "injured", "victim", {"amount": 10, "cause": "fall", "attacker": "brute"})  # no violence
    world = facts([ME, brute, victim], [hit, bite, fall])
    assert check(world, "me", "deeds_judged", group="band_a", days=7) == (False, 0)
    assert check(world, "me", "no_witnessed_deed", group="band_b", days=7) == (False, 14)  # 1 day of 7


def test_seizures_guilty_counts_their_seizures_followed_by_a_judgement() -> None:
    goro = person("goro")
    events: list[Told] = [
        (100, "seized", "goro", {"person": "a", "held": True}),
        (200, "judged", "masanori", {"person": "a", "sentence": "fine"}),  # counts
        (300, "seized", "goro", {"person": "b", "held": True}),
        (310, "seized", "kenji", {"person": "b", "held": True}),
        (400, "judged", "masanori", {"person": "b", "sentence": "fine"}),  # Kenji's seizure, not Goro's
        (500, "seized", "kenji", {"person": "c", "held": True}),
        (600, "judged", "masanori", {"person": "c", "sentence": "confine"}),  # not his
        (650, "seized", "goro", {"person": "e", "held": False}),  # e twisted free: no seizure
        (660, "judged", "masanori", {"person": "e", "sentence": "fine"}),
        (700, "seized", "goro", {"person": "d", "held": True}),  # not judged yet
    ]
    assert check(facts([goro], events), "goro", "seizures_guilty", count=3) == (False, 33)
    assert check(facts([goro], events), "goro", "seizures_guilty", count=1) == (True, 100)


def test_coins_at_least() -> None:
    rich = person("rich", inventory={"coins": 150})
    assert check(facts([rich]), "rich", "coins_at_least", count=300) == (False, 50)
    assert check(facts([rich]), "rich", "coins_at_least", count=150) == (True, 100)


def test_no_tax_owed_counts_days_since_the_household_was_last_overdue() -> None:
    overdue = {"household": "house-1", "rice": 3, "coins": 0, "owed_rice": 3, "owed_coins": 0, "days": 1}
    other = {**overdue, "household": "house-2"}
    events = [(NOW - 5 * DAY, "tax_overdue", None, overdue), (NOW - 2 * DAY, "tax_overdue", None, overdue)]
    world = facts([ME], [*events, (NOW - DAY, "tax_overdue", None, other)])
    assert check(world, "me", "no_tax_owed", days=7) == (False, 29)  # 2 days of 7
    assert check(world, "me", "no_tax_owed", days=2) == (True, 100)
    assert check(facts([ME], tick=3 * DAY), "me", "no_tax_owed", days=7) == (False, 43)  # never: since the start


def test_sold_sums_their_sales_of_the_item() -> None:
    def sale(actor: str, item: str, count: int) -> tuple[int, str, str, dict[str, Any]]:
        lots = {"lots": 1, "coins": 25, "stall": "market-stall", "merchant": "fumiko"}
        return (NOW - DAY, "sold", actor, {"item": item, "count": count, **lots})

    events = [sale("me", "cloth", 3), sale("me", "cloth", 4), sale("other", "cloth", 9), sale("me", "rice", 6)]
    bought = (
        NOW,
        "bought",
        "me",
        {"item": "cloth", "count": 5, "lots": 5, "coins": 125, "stall": "s", "merchant": "f"},
    )
    world = facts([ME, person("other")], [*events, bought])
    assert check(world, "me", "sold", item="cloth", count=10) == (False, 70)
    assert check(world, "me", "sold", item="cloth", count=7) == (True, 100)


def test_knows_place_and_people() -> None:
    me = person("me", places={"market": "visited", "band_a_camp": "rough"}, people={"a", "b", "c"})
    world = facts([me, person("a"), person("b"), person("c", "band_a")])
    assert check(world, "me", "knows_place", place="band_a_camp") == (True, 100)
    assert check(world, "me", "knows_place", place="temple") == (False, 0)
    assert check(world, "me", "knows_people", group="town", count=3) == (False, 67)
    assert check(world, "me", "knows_people", group="town", count=2) == (True, 100)


def _moved(item: str, giver: str, receiver: str) -> dict[str, Any]:
    return {
        "item": item,
        "count": 1,
        "source": {"kind": "inventory", "id": giver},
        "destination": {"kind": "inventory", "id": receiver},
    }


def test_gave_crafted_is_half_way_once_crafted_and_done_once_given_after() -> None:
    tetsu, lord = person("tetsu"), person("lord")
    crafted = (500, "crafted", "tetsu", {"recipe": "iron spear", "item": "iron spear", "count": 1, "station": "forge"})
    given_before = (400, "item_moved", "tetsu", _moved("iron spear", "tetsu", "lord"))
    to_someone_else = (600, "item_moved", "tetsu", _moved("iron spear", "tetsu", "kenji"))
    other_item = (600, "item_moved", "tetsu", _moved("iron axe", "tetsu", "lord"))
    stall_buys = (650, "item_moved", "tetsu", {**_moved("iron spear", "tetsu", "x"), "destination": {"kind": "store"}})
    args: dict[str, str | int] = {"item": "iron spear", "to": "lord"}
    assert check(facts([tetsu, lord], [given_before]), "tetsu", "gave_crafted", **args) == (False, 0)
    early = [given_before, crafted, to_someone_else, other_item, stall_buys]
    assert check(facts([tetsu, lord], early), "tetsu", "gave_crafted", **args) == (False, 50)
    given = (700, "item_moved", "tetsu", _moved("iron spear", "tetsu", "lord"))
    assert check(facts([tetsu, lord], [*early, given]), "tetsu", "gave_crafted", **args) == (True, 100)


def test_tended_people_counts_different_people() -> None:
    events = [(1, "tended", "me", {"person": p, "health": 5}) for p in ("a", "a", "b")]
    events.append((2, "tended", "other", {"person": "c", "health": 5}))
    world = facts([ME], events)
    assert check(world, "me", "tended_people", count=10) == (False, 20)
    assert check(world, "me", "tended_people", count=2) == (True, 100)


def _hunger(level: str, worse: bool, value: float = 60.0) -> dict[str, Any]:
    return {"need": "hunger", "level": level, "value": value, "worse": worse}


def test_never_starving_counts_days_since_any_member_starved() -> None:
    kin = [person("a", "band_a"), person("b", "band_a"), person("z", "band_b")]
    events = [
        (NOW - 4 * DAY, "need_changed", "a", _hunger("starving", True, 90)),
        (NOW - 3 * DAY, "need_changed", "a", _hunger("hungry", False)),  # left starving: still starving until then
        (NOW - 3 * DAY, "need_changed", "b", _hunger("hungry", True)),  # hungry is not starving
        (NOW - 2 * DAY, "need_changed", "b", {"need": "thirst", "level": "parched", "value": 90, "worse": True}),
        (NOW - DAY, "need_changed", "z", _hunger("starving", True, 90)),  # another band
    ]
    world = facts([ME, *kin], events)
    assert check(world, "me", "never_starving", group="band_a", days=7) == (False, 43)  # 3 days of 7
    assert check(world, "me", "never_starving", group="band_a", days=3) == (True, 100)
    starving_now = facts([ME, person("a", "band_a", body=(95.0, 10.0, 90.0, 100.0))], events[:1])
    assert check(starving_now, "me", "never_starving", group="band_a", days=7) == (False, 0)
    dead = facts([ME, person("a", "band_a", body=(95.0, 10.0, 90.0, 100.0), alive=False)], tick=7 * DAY)
    assert check(dead, "me", "never_starving", group="band_a", days=7) == (True, 100)  # the dead feel nothing


def test_hunger_below_counts_days_since_they_felt_the_word_or_worse() -> None:
    pip = person("pip", "band_b")
    hungry = [(NOW - 3 * DAY, "need_changed", "pip", _hunger("hungry", True))]
    assert check(facts([ME, pip], hungry), "me", "hunger_below", who="pip", word="hungry", days=7) == (False, 43)
    fed_again = [*hungry, (NOW - DAY, "need_changed", "pip", _hunger("fed", False, 59))]
    assert check(facts([ME, pip], fed_again), "me", "hunger_below", who="pip", word="hungry", days=7) == (False, 14)
    assert check(facts([ME, pip], fed_again), "me", "hunger_below", who="pip", word="starving", days=7) == (True, 100)
    hungry_now = person("pip", "band_b", body=(65.0, 10.0, 90.0, 100.0))
    assert check(facts([ME, hungry_now]), "me", "hunger_below", who="pip", word="hungry", days=7) == (False, 0)


def test_owns_carried_or_in_the_household_chest() -> None:
    world = facts([ME, person("other", home="house-2")], stores={"house-1-chest": {"iron axe": 1}})
    assert check(world, "me", "owns", item="iron axe") == (True, 100)
    assert check(world, "other", "owns", item="iron axe") == (False, 0)
    carrying = person("other", home="house-2", inventory={"iron axe": 1})
    assert check(facts([carrying]), "other", "owns", item="iron axe") == (True, 100)


def test_is_leader_of_their_own_group_while_alive() -> None:
    def chief(**fields: Any) -> ReplayCitizen:
        return person("ama", "band_a", member=Member(group="band_a", age=40, home=None, base_rank=2, **fields))

    assert check(facts([chief(titles=["leader"])]), "ama", "is_leader", group="band_a") == (True, 100)
    assert check(facts([chief()]), "ama", "is_leader", group="band_a") == (False, 0)
    assert check(facts([chief(titles=["leader"])]), "ama", "is_leader", group="band_b") == (False, 0)
    dead = person("ama", "band_a", alive=False, member=Member("band_a", 40, None, 2, ["leader"]))
    assert check(facts([dead]), "ama", "is_leader", group="band_a") == (False, 0)
    lord = person("lord", member=Member("town", 55, None, 3, ["lord"]))
    assert check(facts([lord]), "lord", "is_leader", group="town") == (True, 100)


def _started(number: int, action: str, target: str | None = None) -> dict[str, Any]:
    told = {"kind": "person", "id": target, "name": "x"} if target else None
    return {"number": number, "action": action, "args": {}, "label": "", "target": told}


def _ended(number: int, action: str) -> dict[str, Any]:
    return {"number": number, "action": action, "outcome": "done", "text": ""}


def test_followed_hunt_needs_a_follow_of_a_hunter_while_they_hunt() -> None:
    kid, hunter = person("kid", "band_a"), person("hunter", "band_a")
    hunt = [
        (100, "action_started", "hunter", _started(1, "hunt")),
        (200, "action_finished", "hunter", _ended(1, "hunt")),
    ]
    before = [
        (50, "action_started", "kid", _started(1, "follow", "hunter")),
        (90, "action_interrupted", "kid", _ended(1, "follow")),
    ]
    other = [(150, "action_started", "kid", _started(2, "follow", "someone"))]
    assert check(facts([kid, hunter], [*before, *hunt, *other]), "kid", "followed_hunt") == (False, 0)
    during = [(180, "action_started", "kid", _started(3, "follow", "hunter"))]  # still following at NOW
    assert check(facts([kid, hunter], [*before, *hunt, *during]), "kid", "followed_hunt") == (True, 100)


def test_no_witnessed_deed_counts_days_since_a_member_s_seen_deed() -> None:
    raider, farmer = person("raider", "band_b"), person("farmer", home="farmhouse-1")
    seen = (NOW - 2 * DAY, "stole", "raider", _theft("farmhouse-1", ["farmer"]))
    unseen = (NOW - DAY, "stole", "raider", _theft("farmhouse-1", []))
    trespass = (
        NOW - 3 * DAY,
        "trespassed",
        "raider",
        {"kind": "walls", "owner": "town", "place": "x", "witnesses": ["farmer"]},
    )
    world = facts([ME, raider, farmer], [trespass, seen, unseen])
    assert check(world, "me", "no_witnessed_deed", group="band_b", days=7) == (False, 29)
    assert check(world, "me", "no_witnessed_deed", group="town", days=7) == (True, 100)


def test_an_ambition_is_the_mean_of_its_checks_and_done_when_all_are_met() -> None:
    rich = person("rich", inventory={"coins": 150}, places={"market": "visited"})
    ambition = Ambition(
        text="rich and worldly",
        all_of=[
            AmbitionClause(check="coins_at_least", args={"count": 300}),
            AmbitionClause(check="knows_place", args={"place": "market"}),
        ],
    )
    progress = ambition_progress(facts([rich]), rich, ambition)
    assert (progress.progress, progress.done, [c.progress for c in progress.clauses]) == (75, False, [50, 100])
    richer = person("rich", inventory={"coins": 300}, places={"market": "visited"})
    assert ambition_progress(facts([richer]), richer, ambition).model_dump(include={"progress", "done"}) == {
        "progress": 100,
        "done": True,
    }
    almost = person("rich", inventory={"coins": 299}, places={"market": "visited"})
    assert ambition_progress(facts([almost]), almost, ambition).progress == 99  # never 100 % until done


def test_every_cast_ambition_reads_on_the_cast_s_first_tick(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim(seed=1)
    cast = load_citizens(CITIZENS)
    for spec in cast.citizens:
        sim.add_citizen(spec)
    sim.drain()
    state = from_snapshot(take_snapshot(sim.state))
    ambitions = cast_ambitions()
    world = Facts(tick=0, state=state, events=[])
    progress = {
        spec.id: ambition_progress(world, state.citizens[spec.id], ambitions[spec.id]) for spec in cast.citizens
    }
    assert len(progress) == 22
    assert progress["hana"].progress == 0  # she hasn't found band A's camp
    assert (progress["fumiko"].progress, progress["fumiko"].done) == (100, True)  # her 500 coins of 300
    assert progress["tokuji"].progress == 0  # owing no tax for seven days starts at none
