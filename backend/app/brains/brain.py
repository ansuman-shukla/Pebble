"""A scripted utility brain for one citizen (02-simulation, "Scripted brains").

At each decision point (the last action ended or was interrupted) it looks around, scores its options from needs,
danger, time of day (the local sun, as perception words it) and role, and starts the best one. It acts only through
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

from app.brains.profile import BrainProfile
from app.brains.routines import ROUTINES, Context, Option
from app.brains.senses import (
    Needs,
    at,
    at_home,
    carried_food,
    danger,
    fire_here,
    is_name,
    phase,
    sees_thing,
    water_here,
    water_in_view,
)
from app.core.rng import Rng
from app.world_api.facade import WorldApi
from app.world_api.models import Perception

STOREHOUSES = "the storehouses"
WELL = "the well"
FIRE = "the fire pit"
GREET_CHANCE = 0.5
GREET_REACH = ("right beside you", "a few paces", "close by")
EAT_ORDER = ("berries", "nuts", "roots", "rice", "dried meat")  # what spoils first goes first; dried meat keeps
RAW = ("meat", "fish")  # roasted by a fire, else eaten raw only when there's nothing else (it can make you sick)


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
        perception = api.look_around()
        if perception.place == "asleep":  # woken but still lying there: the sleep goes on
            return
        if notes.get("asleep"):
            notes["asleep"] = False
            notes["greeted"] = []  # a new day: greet people again
            notes["chores"] = []
        options = self.options(perception)
        best = max(options, key=lambda option: option.score)
        if best.score < 60 and self.socialise(perception):
            handle = api.wait(2)  # stand and talk a moment
        else:
            handle = best.start()
            notes["last"] = best.name
        if handle.result is not None and handle.result.outcome != "interrupted":
            previous = notes.get("instant")
            streak = (previous if isinstance(previous, int) else 0) + 1
            notes["instant"] = streak
            notes["failed"] = notes.get("last") if handle.result.outcome == "failed" else None
            if handle.result.outcome == "failed" or streak >= 2:
                handle = api.wait(10 + 5 * self.pick(4))  # nothing to do right now: look again in a while
                notes["instant"] = 0
        else:
            notes["instant"] = 0
            notes["failed"] = None
        notes["action"] = handle.number
        if best.name == "sleep" and handle.result is None:
            notes["asleep"] = True

    # --- options ---

    def options(self, p: Perception) -> list[Option]:
        needs = Needs.read(p.you.feeling)
        now = phase(p)
        ctx = Context(self.api, self.profile, p, needs, now, self.chance, self.pick)
        options = [Option(1, "idle", lambda: self.api.wait(15))]
        behind_walls = self.profile.region == "town" and at(p, self.profile.home_area)  # walls keep animals out
        if danger(p) is not None and not behind_walls and fire_here(p) not in ("burning", "low"):  # fire too
            options.append(Option(200, "flee", self.api.flee))
        thirst = self.thirst_option(p, needs, now)
        if thirst is not None:
            options.append(thirst)
        hunger = self.hunger_option(p, needs, now)
        if hunger is not None:
            options.append(hunger)
        options += self.rest_options(p, needs, now)
        options += ROUTINES[self.profile.routine](ctx)
        return options

    def thirst_option(self, p: Perception, needs: Needs, now: str) -> Option | None:
        before_bed = now in ("dusk", "night") and needs.thirst >= 1
        if needs.thirst < 2 and not before_bed and not (now == "morning" and needs.thirst >= 1):
            return None
        score = {0: 0.0, 1: 50.0, 2: 80.0, 3: 110.0}[needs.thirst]
        arrived = self.api.notes.get("last") == "go drink" and water_in_view(p)  # at the shore of a lake or river
        if water_here(p) or arrived or (self.profile.region == "town" and at(p, WELL)):
            return Option(score, "drink", self.api.drink)
        if self.profile.region == "town":
            return Option(score, "go drink", lambda: self.api.walk_to_place(WELL))
        if water_in_view(p) or self.api.notes.get("last") != "go drink":
            # the water may be in sight without being among the things noticed first; if not, the walk fails
            return Option(score, "go drink", lambda: self.api.walk_to_thing("water"))
        return Option(score - 20, "go home", lambda: self.api.walk_to_place("home"))  # the water is near camp

    def hunger_option(self, p: Perception, needs: Needs, now: str) -> Option | None:
        mealtime = now in ("morning", "dusk") and needs.hunger >= 1
        if needs.hunger < 2 and not mealtime:
            return None
        score = {1: 45.0, 2: 85.0, 3: 105.0}[needs.hunger]
        food = carried_food(p)
        raw = [name for name in RAW if name in food]
        if raw and fire_here(p) in ("burning", "low"):
            return Option(score + 1, "eat by the fire", lambda: self.api.eat(raw[0]))
        cooked = [name for name in EAT_ORDER if name in food]
        if cooked or (raw and needs.hunger >= 2):
            item = cooked[0] if cooked else raw[0]
            return Option(score, "eat", lambda: self.api.eat(item))
        if self.profile.region == "town":
            # in the storehouses' yard but out of reach of a door (stopped short): walk up to them first
            if at(p, STOREHOUSES) and self.api.notes.get("failed") != "eat":
                return Option(score, "eat", lambda: self.api.eat("rice"))
            return Option(score - 2, "go eat", lambda: self.api.walk_to_place(STOREHOUSES))
        return None  # bands go foraging (their routine scores it up when hungry)

    def rest_options(self, p: Perception, needs: Needs, now: str) -> list[Option]:
        options: list[Option] = []
        if now == "night":
            if at_home(p):
                options.append(Option(70, "sleep", self.api.sleep))
            else:
                options.append(Option(70, "go home", lambda: self.api.walk_to_place("home")))
        elif needs.tiredness >= 3:
            options.append(Option(90, "sleep", self.api.sleep))
        elif needs.tiredness >= 2:
            options.append(Option(35, "rest", lambda: self.api.rest(30)))
        if now == "dusk":
            if self.profile.region == "town":
                if at_home(p):
                    options.append(Option(40, "rest at home", lambda: self.api.rest(30)))
                else:
                    options.append(Option(40, "go home", lambda: self.api.walk_to_place("home")))
            else:
                fire = sees_thing(p, FIRE)
                if fire is not None and fire.where.startswith(("right beside you", "a few paces")):
                    options.append(Option(40, "rest by the fire", lambda: self.api.rest(30)))
                elif fire is not None:
                    options.append(Option(40, "go to the fire", lambda: self.api.walk_to_thing(FIRE)))
                else:
                    options.append(Option(40, "go home", lambda: self.api.walk_to_place("home")))
        return options

    # --- greetings ---

    def socialise(self, p: Perception) -> bool:
        """Reply to someone who greeted you by name, or greet a known person close by (once a day each)."""
        greeted = self.api.notes.setdefault("greeted", [])
        if not isinstance(greeted, list):
            raise TypeError("greeted must be a list")
        name = self.profile.name
        for heard in p.heard:
            if is_name(heard.who) and name.lower() in heard.words.lower() and heard.who not in greeted:
                greeted.append(heard.who)
                self.api.say(self.reply(heard.who, p))
                return True
        for person in p.people:
            label = person.label
            if is_name(label) and label not in greeted and person.where.startswith(GREET_REACH):
                if person.doing == "asleep":
                    continue
                greeted.append(label)
                if self.chance(GREET_CHANCE):
                    self.api.say(self.greeting(label, p))
                    return True
        return False

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
