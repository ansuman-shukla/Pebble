"""A scripted utility brain for one citizen (02-simulation, "Scripted brains").

At each decision point (the last action ended or was interrupted) it looks around, scores its options from needs,
danger, time of day (the local sun, as perception reports it) and role, and starts the best one. It acts only through
`WorldApi`, exactly as an agent mind will; its working memory lives in `api.notes` so a resumed run continues the
same way.

```
 tick ─▶ alive? ─▶ action still running? ── yes ─▶ nothing to do
                        │ no (done, interrupted, or none yet)
                        ▼
              look_around ─▶ reply/greet ─▶ score options ─▶ start the best ─▶ failed at once? ─▶ wait a little
              danger (flee) > thirst/hunger > night: home + sleep > dusk: eat, home/fire > role routine
```
"""

from dataclasses import replace
from functools import partial

from pydantic import JsonValue

from app.brains import justice
from app.brains.profile import BrainProfile
from app.brains.routines import ROUTINES, Context, Option
from app.brains.senses import (
    DISTANCE,
    NIGHT_HUNGER,
    NIGHT_THIRST,
    Needs,
    at,
    at_home,
    beside,
    carried_food,
    carries,
    compass_word,
    danger,
    desperate,
    fire_here,
    fire_in_view,
    harmful_by_morning,
    is_name,
    near,
    phase,
    prowler,
    told_full,
    water_here,
    water_in_view,
    water_way,
)
from app.brains.town import TOWN_ROUTINES
from app.core.rng import Rng
from app.world_api.facade import ActionHandle, WorldApi
from app.world_api.models import GestureKind, Pace, Perception

STOREHOUSES = "the storehouses"
WELL = "the well"
FIRE = "the fire pit"
HURT = ("weak and aching", "close to death")  # how a body that has lost half its health feels
CHAT_CHANCE = 0.3  # with someone greeted already in earshot and nothing pressing, a word in passing this often
EAT_ORDER = ("berries", "nuts", "roots", "rice", "dried meat")  # what spoils first goes first; dried meat keeps
MOVING = frozenset({"walk_to", "follow", "flee", "hunt", "attack", "rest", "sleep"})  # they move the body
RAW = ("meat", "fish")  # roasted by a fire, else eaten raw only when there's nothing else (it can make you sick)
BEDTIME = 75.0  # a drink or a meal before sleeping (sleep scores 70) when the night would leave you parched or starving
BEDTIME_TRIES = 12  # decisions a night spent on it before giving up and sleeping (the water not found in the dark)


class UtilityBrain:
    def __init__(self, api: WorldApi, profile: BrainProfile, seed: int) -> None:
        self.api = api
        self.profile = profile
        notes = api.notes
        if "rng" not in notes:
            notes["rng"] = str(Rng.for_subsystem(seed, f"brain:{profile.citizen_id}").state)

    # --- memory ---

    def _rng(self) -> Rng:
        return Rng(int(str(self.api.notes["rng"])))

    def chance(self, p: float) -> bool:
        rng = self._rng()
        hit = rng.random() < p
        self.api.notes["rng"] = str(rng.state)
        return hit

    def pick(self, count: int) -> int:
        rng = self._rng()
        index = rng.randint(0, count - 1)
        self.api.notes["rng"] = str(rng.state)
        return index

    # --- the loop ---

    def tick(self) -> None:
        """Called before every engine tick: decide only when there's nothing running."""
        if not self.api.alive:
            return
        number = self.api.notes.get("action")
        if isinstance(number, int) and self.api.handle(number).result is None:
            return
        self.decide()

    def decide(self) -> None:
        api, notes = self.api, self.api.notes
        self.note_arrival()
        again = self.eat_or_drink_again()
        if again is not None:
            notes["action"] = again.number
            return
        perception = api.look_around()
        if perception.place == "asleep":  # woken but still lying there: the sleep goes on
            return
        if notes.get("asleep"):
            notes["asleep"] = False
            notes["greeted"] = []  # a new day: greet people again
            notes["chores"] = []
            notes.pop("tempted", None)
            notes.pop("chest empty", None)  # look in the chest again today
            notes.pop("full", None)  # carrying words are rough: a little eaten may not change them, so try again
            notes.pop("goal", None)  # a new day: say what you're after again
            notes.pop("bedtime", None)
        number = notes.get("action")
        if isinstance(number, int) and told_full(api.handle(number).result):  # the load filled as it went on
            notes["full"] = list(perception.you.carrying)
        way = water_way(perception)
        if way is not None and self.profile.region != "town" and at_home(perception):
            notes["water_way"] = way  # which way the camp's water lies from home (only from there), for the dark
        options = self.options(perception)
        best = max(options, key=lambda option: option.score)
        if best.score < 60 and self.socialise(perception):
            handle = api.wait(2)  # stand and talk a moment
        else:
            self.aim(best)
            handle = best.start()
            notes["last"], notes["chosen"] = best.name, handle.number
        if handle.result is not None and handle.result.outcome != "interrupted":
            previous = notes.get("instant")
            streak = (previous if isinstance(previous, int) else 0) + 1
            notes["instant"] = streak
            notes["failed"] = notes.get("last") if handle.result.outcome == "failed" else None
            if told_full(handle.result):
                notes["full"] = list(perception.you.carrying)
            if handle.result.outcome == "failed" or streak >= 2:
                handle = api.wait(10 + 5 * self.pick(4))  # nothing to do right now: look again in a while
                notes["instant"] = 0
        else:
            notes["instant"] = 0
            notes["failed"] = None
        notes["action"] = handle.number
        if best.name == "sleep" and handle.result is None:
            notes["asleep"] = True

    def note_arrival(self) -> None:
        """Remember where the last walk chosen ended (`arrived`: its option's name) until the body moves again: any
        chosen action that moves it (another walk, a walk cut short, a follow, a flee, a hunt, a seat or a bed taken)
        forgets it, while standing there (work, talk, waiting, eating) keeps it."""
        notes = self.api.notes
        number = notes.get("chosen")
        result = self.api.handle(number).result if isinstance(number, int) else None
        if result is None or result.action not in MOVING:
            return
        notes["arrived"] = notes.get("last") if result.action == "walk_to" and result.outcome == "done" else None

    def aim(self, option: Option) -> None:
        """Say to yourself what you're after (`set_goal`, free and seen only by spectators) whenever a choice serves a
        new aim; the steps of one aim (walk there, then work) keep it."""
        goal: list[JsonValue] = [option.aim, option.driver]
        if option.aim and self.api.notes.get("goal") != goal:
            self.api.notes["goal"] = goal
            self.api.set_goal(option.aim, option.driver)

    def eat_or_drink_again(self) -> ActionHandle | None:
        """After a meal or a drink, feel whether it was enough (`check_self`) before looking about: still hungry with
        food left (the berries ran out, there are nuts), eat on; still thirsty by the water, drink on."""
        notes = self.api.notes
        number = notes.get("action")
        last = notes.get("last")
        if last not in ("eat", "eat by the fire", "drink") or not isinstance(number, int):
            return None
        result = self.api.handle(number).result
        if result is None or result.outcome != "done":
            return None
        you = self.api.check_self()
        needs = Needs.read(you.feeling)
        if last == "drink":
            return self.api.drink() if needs.thirst >= 1 else None
        food = carried_food(you)
        left = [name for name in EAT_ORDER if name in food]
        return self.api.eat(left[0]) if needs.hunger >= 1 and left else None

    # --- options ---

    def options(self, p: Perception) -> list[Option]:
        needs = Needs.read(p.you.feeling)
        now = phase(p)
        pace = self.pace(p, needs)
        ctx = Context(self.api, self.profile, p, needs, now, self.chance, self.pick, pace)
        options = [Option(1, "idle", lambda: self.api.wait(15))]
        behind_walls = self.profile.region == "town" and at(p, self.profile.home_area)  # walls keep animals out
        threat = danger(p)
        if threat is not None and not behind_walls and fire_here(p) not in ("burning", "low"):  # fire too
            hurt = any(word in p.you.feeling for word in HURT)  # bitten badly already: no more fighting, run
            if carries(p, "spear") and not hurt and DISTANCE[threat.nearness] in ("here", "near", "close"):
                aim = f"Drive off {threat.label}"
                options.append(Option(200, "fight off", partial(self.api.attack, threat.label), aim, "danger"))
            else:
                options.append(Option(200, "flee", self.api.flee, f"Get away from {threat.label}", "danger"))
        options += justice.options(ctx)
        for need in (self.thirst_option(p, needs, now), self.hunger_option(p, needs, now)):
            if need is not None:
                options.append(self.before_bed(need, needs, now))
        options += self.rest_options(p, needs, now, pace)
        routine = TOWN_ROUTINES.get(self.profile.routine) or ROUTINES[self.profile.routine]
        options += routine(ctx)
        return options

    def pace(self, p: Perception, needs: Needs) -> Pace:
        """Run only when desperate (starving, parched) or with a predator prowling in view out in the open; running
        tires and parches, so nobody runs about their day (10 §4.1)."""
        exposed = not (self.profile.region == "town" and at(p, self.profile.home_area))
        if desperate(needs) or (exposed and prowler(p) is not None and fire_here(p) not in ("burning", "low")):
            return "run"
        return "walk"

    def thirst_option(self, p: Perception, needs: Needs, now: str) -> Option | None:
        before_bed = now in ("dusk", "night") and needs.thirst >= 1
        if needs.thirst < 2 and not before_bed and not (now == "morning" and needs.thirst >= 1):
            return None
        score = {0: 0.0, 1: 50.0, 2: 80.0, 3: 110.0}[needs.thirst]
        pace: Pace = "run" if desperate(needs) else "walk"
        option = partial(Option, aim="Get a drink", driver="thirst")
        arrived = self.api.notes.get("last") == "go drink" and water_in_view(p)  # at the shore of a lake or river
        # at the well but out of reach of it (stopped short, or brought there by someone): walk up to it first
        at_well = self.profile.region == "town" and at(p, WELL) and self.api.notes.get("failed") != "drink"
        if water_here(p) or arrived or at_well:
            return option(score, "drink", self.api.drink)
        if self.profile.region == "town":
            return option(score, "go drink", lambda: self.api.walk_to_place(WELL, pace))
        way = compass_word(self.api.notes.get("water_way"))
        on_the_way = self.api.notes.get("last") == "go towards the water" and near(p, self.profile.home_area)
        if way is not None and not water_in_view(p) and (at_home(p) or on_the_way):
            # the camp's water out of sight (dark falls early under trees): set out from home the way it lies from
            # there, a few steps at a time, until it comes into view
            return option(score, "go towards the water", lambda: self.api.walk_towards(way, "a few steps", pace))
        if water_in_view(p) or self.api.notes.get("last") != "go drink":
            # the water may be in sight without being among the things noticed first; if not, the walk fails
            return option(score, "go drink", lambda: self.api.walk_to_thing("water", pace))
        return option(score - 20, "go home", lambda: self.api.walk_to_place("home", pace))  # the water is near camp

    def before_bed(self, option: Option, needs: Needs, now: str) -> Option:
        """At night a drink or a meal comes before sleep when the night would otherwise carry thirst or hunger, as
        roughly as the body tells it, to where it hurts; but only for `BEDTIME_TRIES` such choices a night, so someone
        who can't find the water in the dark goes to sleep rather than search all night."""
        level, rise = (needs.thirst, NIGHT_THIRST) if option.driver == "thirst" else (needs.hunger, NIGHT_HUNGER)
        tries = self.api.notes.get("bedtime")
        spent = tries if isinstance(tries, int) else 0
        if now != "night" or not harmful_by_morning(level, rise) or spent >= BEDTIME_TRIES:
            return option

        def start() -> ActionHandle:
            self.api.notes["bedtime"] = spent + 1
            return option.start()

        return replace(option, score=max(option.score, BEDTIME), start=start)

    def hunger_option(self, p: Perception, needs: Needs, now: str) -> Option | None:
        mealtime = now in ("morning", "dusk", "night") and needs.hunger >= 1  # night: a bite before bed
        if needs.hunger < 2 and not mealtime:
            return None
        score = {1: 45.0, 2: 85.0, 3: 105.0}[needs.hunger]
        pace: Pace = "run" if desperate(needs) else "walk"
        option = partial(Option, aim="Get something to eat", driver="hunger")
        food = carried_food(p.you)
        raw = [name for name in RAW if name in food]
        if raw and fire_here(p) in ("burning", "low"):
            return option(score + 1, "eat by the fire", lambda: self.api.eat(raw[0]))
        cooked = [name for name in EAT_ORDER if name in food]
        if cooked or (raw and needs.hunger >= 2):
            item = cooked[0] if cooked else raw[0]
            return option(score, "eat", lambda: self.api.eat(item))
        if self.profile.region != "town":
            return None  # bands go foraging (their routine scores it up when hungry)
        failed = self.api.notes.get("failed") == "eat"
        if self.profile.granary:  # the lord's granary feeds them
            # in the storehouses' yard but out of reach of a door (stopped short): walk up to them first
            if at(p, STOREHOUSES) and not failed:
                return option(score, "eat", lambda: self.api.eat("rice"))
            return option(score - 2, "go eat", lambda: self.api.walk_to_place(STOREHOUSES, pace))
        if at_home(p) and failed:
            self.api.notes["chest empty"] = True  # nothing to eat at home today
        starving = needs.hunger >= 3 and not carries(p, "coins") and self.api.notes.get("chest empty") is True
        if starving and self.tempted():  # no food carried, none at home, no coins to buy any
            return self.steal_option(p, score, pace)
        if not at_home(p):  # the household's own rice is in the chest at home
            return option(score - 2, "go eat", lambda: self.api.walk_to_place("home", pace))
        return None if failed else option(score, "eat", lambda: self.api.eat("rice"))

    def tempted(self) -> bool:
        """A starving town citizen with no food (carried or in the chest at home) and no coins takes rice that isn't
        theirs with p = 1 - honesty (§3.6), rolled once a waking day."""
        notes = self.api.notes
        if "tempted" not in notes:
            notes["tempted"] = self.chance(1.0 - self.profile.honesty)
        return notes["tempted"] is True

    def steal_option(self, p: Perception, score: float, pace: Pace) -> Option:
        """Take five measures of rice from the nearest store (the storehouses) and eat."""
        option = partial(Option, aim="Take rice to eat", driver="hunger")
        if not at(p, STOREHOUSES):
            return option(score - 2, "go take rice", lambda: self.api.walk_to_place(STOREHOUSES, pace))

        def take_and_eat() -> ActionHandle:
            self.api.pick_up("5 rice")
            return self.api.eat("rice")

        return option(score, "take rice", take_and_eat)

    def rest_options(self, p: Perception, needs: Needs, now: str, pace: Pace) -> list[Option]:
        options: list[Option] = []
        home = lambda: self.api.walk_to_place("home", pace)  # noqa: E731  # a tiny closure reads best inline
        if now == "night":
            if at_home(p):
                options.append(Option(70, "sleep", self.api.sleep, "Sleep at home", "night"))
            else:
                options.append(Option(70, "go home", home, "Sleep at home", "night"))
        elif needs.tiredness >= 3:
            options.append(Option(90, "sleep", self.api.sleep, "Sleep off the weariness", "rest"))
        elif needs.tiredness >= 2:
            options.append(Option(35, "rest", lambda: self.api.rest(30), "Rest a while", "rest"))
        if now == "dusk":
            if self.profile.region == "town":
                evening = partial(Option, 40, aim="Spend the evening at home", driver="night")
                if at_home(p):
                    options.append(evening("rest at home", lambda: self.api.rest(30)))
                else:
                    options.append(evening("go home", home))
            else:
                evening = partial(Option, 40, aim="Sit by the fire for the evening", driver="night")
                fire = fire_in_view(p)
                if fire is not None and beside(fire):
                    options.append(evening("rest by the fire", lambda: self.api.rest(30)))
                elif fire is not None:
                    options.append(evening("go to the fire", lambda: self.api.walk_to_thing(FIRE, pace)))
                else:
                    options.append(evening("go home", home))
        return options

    # --- greetings ---

    def socialise(self, p: Perception) -> bool:
        """Reply to someone who greeted you by name, answer a question put to you by name, greet a known person a few
        paces off (once a day each: a bow to your betters, a wave to the rest, and a word), or now and then pass the
        time with someone already greeted, when they're near enough to hear it.

        Only people a few paces off surely hear a normal voice (03: speech carries ~30 m, "close by" reaches 50 m).
        Brains don't shout greetings: a shout carries 150 m and stops everyone's work and sleep there (D97).
        """
        greeted = self.api.notes.setdefault("greeted", [])
        if not isinstance(greeted, list):
            raise TypeError("greeted must be a list")
        name = self.profile.name
        within_earshot = {person.label for person in p.people if beside(person)}
        for heard in p.heard:
            if not (is_name(heard.who) and name.lower() in heard.words.lower()):
                continue
            if heard.who not in within_earshot:
                continue  # they've walked out of earshot
            if heard.who not in greeted:
                greeted.append(heard.who)
                self.api.gesture(self.salute(heard.who), heard.who)
                self.api.say(self.reply(heard.who, p))
                return True
            if heard.words.endswith("?"):
                self.api.say(self.answer(heard.who))
                return True
        awake = [
            person.label
            for person in p.people
            if is_name(person.label) and person.label in within_earshot and person.doing != "asleep"
        ]
        for label in awake:
            if label not in greeted:
                greeted.append(label)
                self.api.gesture(self.salute(label), label)
                self.api.say(self.greeting(label, p))
                return True
        notes = self.api.notes
        if awake and notes.get("chatted") != p.time_of_day and self.chance(CHAT_CHANCE):
            notes["chatted"] = p.time_of_day  # a word in passing at most once each part of the day
            self.api.say(self.small_talk(awake[self.pick(len(awake))], p))
            return True
        return False

    def salute(self, name: str) -> GestureKind:
        """A bow to the lord, a samurai or your band's leader (when they outrank you), a wave to anyone else."""
        return "bow" if self.profile.bows_to(name) else "wave"

    def greeting(self, name: str, p: Perception) -> str:
        now = phase(p)
        if self.profile.region == "town":
            lines = {
                "morning": [f"Good morning, {name}!", f"Morning, {name}. Sleep well?"],
                "day": [f"Hello, {name}!", f"{name}! How goes it?", f"A fine day, isn't it, {name}?"],
                "dusk": [f"Good evening, {name}.", f"{name}, heading home?"],
                "night": [f"Still up, {name}?"],
            }[now]
        else:
            lines = {
                "morning": [f"{name}! You're up.", f"Morning, {name}."],
                "day": [f"Hey, {name}!", f"{name}, there's food this way.", f"Ho, {name}!"],
                "dusk": [f"{name}, come sit by the fire.", f"Evening, {name}."],
                "night": [f"Sleep, {name}."],
            }[now]
        return lines[self.pick(len(lines))]

    def reply(self, name: str, p: Perception) -> str:
        lines = [f"Hello, {name}.", f"And to you, {name}!", f"{name}! Good to see you."]
        if phase(p) == "dusk":
            lines = [f"Good evening, {name}.", f"Rest well, {name}."]
        return lines[self.pick(len(lines))]

    def small_talk(self, name: str, p: Perception) -> str:
        """A word in passing with someone already greeted today; half are questions, which they answer."""
        if self.profile.region == "town":
            lines = [
                f"{name}, how goes the work?",
                f"Have you eaten, {name}?",
                f"The rice is coming on well, {name}.",
                f"Busy day, {name}.",
            ]
        else:
            lines = [
                f"{name}, seen any game?",
                f"Is the fire still going, {name}?",
                f"Stay close to camp, {name}.",
                f"Good picking today, {name}.",
            ]
        if phase(p) == "dusk":
            lines = [f"Long day, {name}.", f"Will you sleep soon, {name}?"]
        return lines[self.pick(len(lines))]

    def answer(self, name: str) -> str:
        lines = [f"Well enough, {name}.", f"Not yet, {name}.", f"Can't complain, {name}."]
        return lines[self.pick(len(lines))]
