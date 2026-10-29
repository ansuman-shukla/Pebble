"""Citizen specs: who someone is and where they start. `data/citizens/citizens.yaml` is the World v1 cast of 22 (the
engine starts new runs with it); `data/citizens/dev.yaml` is a small cast for tests and development.

Besides where someone starts, the World v1 cast carries their society data (10-world-v1 §3.1-3.2): rank and titles,
traits, family, bonds, an ambition the world can check, and starting coins. The systems that use them (society,
ownership, coins, scoreboard) read them from here.
"""

from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import WORLD_DATA_DIR
from app.sim.state import Region
from app.world.geometry import Point

CITIZENS_DATA_DIR = WORLD_DATA_DIR / "citizens"
DEV_CITIZENS = CITIZENS_DATA_DIR / "dev.yaml"
CITIZENS = CITIZENS_DATA_DIR / "citizens.yaml"

Title = Literal["lord", "samurai", "ashigaru", "leader"]
TITLE_RANK: dict[Title, int] = {"lord": 5, "samurai": 4, "leader": 4, "ashigaru": 3}  # §3.2
Kin = Literal["mate", "parent", "child", "sibling", "grandparent", "grandchild", "parent's sibling", "sibling's child"]
KIN_INVERSE: dict[Kin, Kin] = {  # if B is A's <kin>, A is B's <inverse>
    "mate": "mate",
    "parent": "child",
    "child": "parent",
    "sibling": "sibling",
    "grandparent": "grandchild",
    "grandchild": "grandparent",
    "parent's sibling": "sibling's child",
    "sibling's child": "parent's sibling",
}
AmbitionCheck = Literal[
    "store_holds",  # a store holds at least `count` of `item` (optionally only `at` the week's end)
    "standing_at_least",  # `who` (default: themselves) stands at least `value` with `group`
    "deeds_judged",  # every witnessed deed against `group` in the last `days` ended judged
    "seizures_guilty",  # `count` of their seizures were judged guilty
    "coins_at_least",  # they own at least `count` coins
    "no_tax_owed",  # their household owed no tax for `days` days running
    "sold",  # they sold `count` of `item`
    "knows_place",  # they know `place`
    "knows_people",  # they know `count` people of `group` by name
    "gave_crafted",  # they crafted an `item` and gave it to `to`
    "tended_people",  # they tended `count` different people
    "never_starving",  # nobody of `group` starved for `days` days running
    "owns",  # they own an `item`
    "is_leader",  # they lead `group`
    "hunger_below",  # `who` never felt `word` or worse for `days` days running
    "followed_hunt",  # they followed a hunter during a hunt
    "no_witnessed_deed",  # nobody of `group` did a witnessed deed for `days` days running
]
AMBITION_ARGS: dict[AmbitionCheck, tuple[frozenset[str], frozenset[str]]] = {  # (required, optional) arguments
    "store_holds": (frozenset({"store", "item", "count"}), frozenset({"at"})),
    "standing_at_least": (frozenset({"group", "value"}), frozenset({"who"})),
    "deeds_judged": (frozenset({"group", "days"}), frozenset()),
    "seizures_guilty": (frozenset({"count"}), frozenset()),
    "coins_at_least": (frozenset({"count"}), frozenset()),
    "no_tax_owed": (frozenset({"days"}), frozenset()),
    "sold": (frozenset({"item", "count"}), frozenset()),
    "knows_place": (frozenset({"place"}), frozenset()),
    "knows_people": (frozenset({"group", "count"}), frozenset()),
    "gave_crafted": (frozenset({"item", "to"}), frozenset()),
    "tended_people": (frozenset({"count"}), frozenset()),
    "never_starving": (frozenset({"group", "days"}), frozenset()),
    "owns": (frozenset({"item"}), frozenset()),
    "is_leader": (frozenset({"group"}), frozenset()),
    "hunger_below": (frozenset({"who", "word", "days"}), frozenset()),
    "followed_hunt": (frozenset(), frozenset()),
    "no_witnessed_deed": (frozenset({"group", "days"}), frozenset()),
}


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Traits(_Spec):
    """0-1 each; they drive scripted choices (§3.1)."""

    honesty: float = Field(ge=0, le=1)
    generosity: float = Field(ge=0, le=1)
    boldness: float = Field(ge=0, le=1)
    temper: float = Field(ge=0, le=1)


class AmbitionClause(_Spec):
    check: AmbitionCheck
    args: dict[str, str | int] = {}

    @model_validator(mode="after")
    def _check_args(self) -> "AmbitionClause":
        required, optional = AMBITION_ARGS[self.check]
        missing, extra = required - set(self.args), set(self.args) - required - optional
        if missing or extra:
            raise ValueError(f"{self.check}: missing {sorted(missing)}, unknown {sorted(extra)}")
        return self


class Ambition(_Spec):
    """What they strive for, in words, and the world checks that tell when it is reached (all must hold)."""

    text: str = Field(min_length=1)
    all_of: list[AmbitionClause] = Field(min_length=1)


class CitizenSpec(_Spec):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    look: str  # frontend look id (citizen-looks.ts)
    appearance: str  # how strangers see them
    age: int = Field(ge=5, le=100)
    site: str = "town"  # local metres below are around this site's anchor (the town uses its chart)
    at: Point
    home: str | None = None  # a town house placement id, or "<camp site>:<lean-to placement id>"
    knows_places: list[str] = []
    knows_people: list[str] = []
    role: str = ""
    region: Region = "town"  # their group (§3.2: town, band_a, band_b)
    sex: Literal["female", "male"] | None = None
    skills: list[str] = []
    inventory: dict[str, int] = {}  # what they start out carrying
    personality: str = ""  # one line, for the minds of phase B and for spectators
    rank: int = Field(2, ge=1, le=5)  # §3.2: lord 5; samurai, monk, band leader 4; ashigaru, merchant, smith, elders 3
    titles: list[Title] = []
    traits: Traits | None = None
    family: dict[str, Kin] = {}  # citizen id -> what they are to this citizen ("ama: mate")
    bonds: dict[str, int] = {}  # citizen id -> how they feel about each other (-100..100), beyond kin
    ambition: Ambition | None = None
    coins: int = Field(0, ge=0)  # starting purse (mon); joins the inventory once coins are an item kind

    @model_validator(mode="after")
    def _check_society(self) -> "CitizenSpec":
        if self.id in self.family or self.id in self.bonds:
            raise ValueError(f"{self.id} can't be their own kin or bond")
        if any(not -100 <= value <= 100 for value in self.bonds.values()):
            raise ValueError(f"{self.id}: bonds run from -100 to 100")
        if self.titles and self.rank != max(TITLE_RANK[title] for title in self.titles):
            raise ValueError(f"{self.id}: rank {self.rank} doesn't match the titles {self.titles}")
        return self


class CitizensSpec(_Spec):
    citizens: list[CitizenSpec]
    stores: dict[str, dict[str, int]] = {}  # storehouse id -> starting stock
    chests: dict[str, dict[str, int]] = {}  # a home's household chest (keep = the treasury) -> starting stock

    @model_validator(mode="after")
    def _check_links(self) -> "CitizensSpec":
        """Family and bonds name people of this cast; kinship reads the same from both sides, and so does a bond
        both of a pair give."""
        by_id = {citizen.id: citizen for citizen in self.citizens}
        if len(by_id) != len(self.citizens):
            raise ValueError("citizen ids must be unique")
        for citizen in self.citizens:
            for other, kin in citizen.family.items():
                if other not in by_id:
                    raise ValueError(f"{citizen.id}: unknown kin {other}")
                inverse = KIN_INVERSE[kin]
                if by_id[other].family.get(citizen.id) != inverse:
                    raise ValueError(f"{other} is {citizen.id}'s {kin}, so {citizen.id} must be {other}'s {inverse}")
            for other, value in citizen.bonds.items():
                if other not in by_id:
                    raise ValueError(f"{citizen.id}: unknown bond {other}")
                back = by_id[other].bonds.get(citizen.id)
                if back is not None and back != value:
                    raise ValueError(f"{citizen.id} and {other} give their bond differently ({value} vs {back})")
        homes = {citizen.home for citizen in self.citizens}
        if not set(self.chests) <= homes:
            raise ValueError(f"chests of nobody's home: {sorted(set(self.chests) - homes)}")
        return self

    def coins(self) -> int:
        """Every coin the cast starts with: purses and chests (the closed money supply, §2.1)."""
        return sum(citizen.coins for citizen in self.citizens) + sum(
            stock.get("coins", 0) for stock in self.chests.values()
        )


@cache
def load_citizens(path: Path = DEV_CITIZENS) -> CitizensSpec:
    return CitizensSpec.model_validate(yaml.safe_load(path.read_text()))
