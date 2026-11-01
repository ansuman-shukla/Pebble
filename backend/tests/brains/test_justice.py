"""The witness and culprit rules on built perceptions (10 §3.3-3.4): a witness shouts a wrong out once and brings it
to the nearest officer in view; someone wanted runs home when an officer comes into view."""

from typing import Any, cast

from pydantic import JsonValue

from app.brains import justice
from app.brains.profile import BrainProfile, Title, known_titles
from app.brains.routines import Context, Option
from app.brains.senses import Needs
from app.world_api.facade import WorldApi
from app.world_api.models import Nearness, Perception, Seen, SelfView

THIEF = "who stole rice from the racks"
TOWN_TITLES = known_titles([("Kenji", ["samurai"]), ("Masanori", ["lord"])])


class Recorder:
    """A world api that only notes what the brain asked of it."""

    def __init__(self) -> None:
        self.notes: dict[str, JsonValue] = {}
        self.calls: list[tuple[Any, ...]] = []

    def __getattr__(self, name: str) -> Any:
        def call(*args: Any) -> None:
            self.calls.append((name, *args))

        return call


def _person(label: str, nearness: Nearness = "a few paces", **fields: Any) -> Seen:
    return Seen(label=label, where=f"{nearness} to the north", nearness=nearness, **fields)


def _look(*people: Seen, wanted: str | None = None, place: str = "at the market, in The castle town") -> Perception:
    you = SelfView(feeling=[], carrying=[], doing="You are standing about.", wanted=wanted)
    return Perception(
        you=you, place=place, time="It is midday.", time_of_day="midday", people=list(people), animals=[], things=[],
        heard=[],
    )  # fmt: skip


def _ctx(
    look: Perception, role: str = "rice farmer", api: Recorder | None = None, titles: tuple[Title, ...] = ()
) -> tuple[Context, Recorder]:
    recorder = api or Recorder()
    profile = BrainProfile("genzo", "Genzo", role, "town", "The castle town", titled=TOWN_TITLES, titles=titles)
    ctx = Context(cast(WorldApi, recorder), profile, look, Needs(0, 0, 0), "day", lambda _p: False, lambda _n: 0)
    return ctx, recorder


def _one(options: list[Option]) -> Option:
    [option] = options
    return option


def test_a_deed_is_read_from_what_you_know_of_someone() -> None:
    assert justice.known_deed(_person("Kaz", regard=f"distrusted, {THIEF}")) == "stole rice from the racks"
    assert justice.known_deed(_person("Kaz", regard="well regarded")) is None
    assert justice.known_deed(_person("Kaz")) is None
    assert justice.known_deed(_person("Kaz", regard="wholly trusted")) is None


def test_a_witness_shouts_the_wrong_out_once_then_accuses_to_the_officer_beside_them() -> None:
    look = _look(_person("Kaz", regard=THIEF), _person("Kenji"))
    ctx, api = _ctx(look)
    shout = _one(justice.options(ctx))
    assert (shout.score, shout.driver, shout.aim) == (justice.WITNESS, "duty", "Make known what Kaz did")
    assert api.calls == []  # nothing said until the option is chosen
    shout.start()
    assert api.calls == [("say", "Kaz stole rice from the racks!", "shout"), ("wait", 1)]

    api.calls.clear()
    accuse = _one(justice.options(_ctx(look, api=api)[0]))
    assert accuse.name == "accuse Kaz" and accuse.aim == "Tell Kenji what Kaz did"
    accuse.start()
    assert api.calls == [("accuse", "Kaz", "Kenji"), ("wait", 2)]
    assert justice.options(_ctx(look, api=api)[0]) == []  # known and told: never again


def test_with_no_officer_about_the_accusation_waits_then_the_witness_walks_up_to_one() -> None:
    ctx, api = _ctx(_look(_person("Kaz", regard=THIEF), _person("Fumiko")))
    _one(justice.options(ctx)).start()
    assert justice.options(_ctx(_look(_person("Fumiko")), api=api)[0]) == []  # Fumiko is no officer

    far = _look(_person("Masanori", "some way off"), _person("Kenji", "close by", doing="asleep"))
    walk = _one(justice.options(_ctx(far, api=api)[0]))
    api.calls.clear()
    walk.start()
    assert walk.name == "go to Masanori" and api.calls == [("walk_to_person", "Masanori")]
    accuse = _one(justice.options(_ctx(_look(_person("Masanori")), api=api)[0]))
    accuse.start()
    assert ("accuse", "Kaz", "Masanori") in api.calls


def test_officers_seize_rather_than_accuse() -> None:
    look = _look(_person("Kaz", regard=THIEF), _person("Masanori"))
    assert justice.options(_ctx(look, role="samurai retainer", titles=("samurai",))[0]) == []
    assert justice.options(_ctx(look, role="ashigaru of the night watch", titles=("ashigaru",))[0]) == []


def test_someone_wanted_runs_home_when_an_officer_comes_into_view() -> None:
    wanted = "You are wanted in the castle town for theft."
    ctx, api = _ctx(_look(_person("Kenji", "some way off"), wanted=wanted))
    run = _one(justice.options(ctx))
    assert (run.score, run.driver, run.aim) == (justice.CULPRIT, "danger", "Get away from Kenji")
    run.start()
    assert api.calls == [("walk_to_place", "home", "run")]
    assert justice.options(_ctx(_look(_person("Fumiko"), wanted=wanted))[0]) == []
    assert justice.options(_ctx(_look(_person("Kenji", doing="asleep"), wanted=wanted))[0]) == []
    assert justice.options(_ctx(_look(_person("Kenji"), wanted=wanted, place="at your home, in town"))[0]) == []
    assert justice.options(_ctx(_look(_person("Kenji")))[0]) == []  # not wanted: nothing to fear


def test_someone_wanted_runs_rather_than_bring_a_wrong_to_an_officer() -> None:
    look = _look(_person("Kaz", regard=THIEF), _person("Kenji"), wanted="You are wanted in the castle town for theft.")
    assert _one(justice.options(_ctx(look)[0])).name == "run home"


def test_a_victim_shouts_the_wrong_done_to_them_in_the_first_person() -> None:
    """Regression (K1): the look says "who struck you"; shouted out it is "Kaz struck me!", not "Kaz struck you!"."""
    ctx, api = _ctx(_look(_person("Kaz", regard="who struck you and stole rice from your chest")))
    _one(justice.options(ctx)).start()
    assert ("say", "Kaz struck me and stole rice from my chest!", "shout") in api.calls
    assert justice.first_person("stole rice from the racks") == "stole rice from the racks"
