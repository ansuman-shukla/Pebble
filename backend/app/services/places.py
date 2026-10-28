"""Names for ids and spots, as spectators read them: places, homes, storehouses and "where is this point".

Built from the simulation's static world (the same places and structures citizens use), once per api process.
"""

import threading
from dataclasses import dataclass

from pydantic import BaseModel
from sqlmodel import Session

from app.sim.vec import Vec3
from app.sim.world import Place, SimWorld, load_sim_world
from app.world.store import WorldGenerator


class PlaceRef(BaseModel):
    id: str
    name: str


@dataclass(frozen=True)
class PlaceIndex:
    world: SimWorld

    def place_name(self, place_id: str) -> str:
        place = self.world.places.get(place_id)
        return place.name if place is not None else place_id

    def place(self, place_id: str) -> PlaceRef:
        return PlaceRef(id=place_id, name=self.place_name(place_id))

    def structure_name(self, structure_id: str) -> str:
        """ "the keep", "a house in the castle town", "a lean-to at Band A camp"."""
        structure = self.world.structures.get(structure_id)
        if structure is None:
            return self.place_name(structure_id)
        if structure.label.startswith("a "):
            site = self.place_name(structure.site).removeprefix("The ")  # "The castle town" mid-sentence
            return f"{structure.label} {'in the' if structure.site == 'town' else 'at'} {site}"
        return structure.label

    def is_storehouse(self, store_id: str) -> bool:
        structure = self.world.structures.get(store_id)
        return structure is not None and structure.kind == "storehouse"

    def store_name(self, store_id: str) -> str:
        """A storehouse or a field's store (fields are places: "the rice fields")."""
        if self.is_storehouse(store_id):
            return "the storehouse"
        return self.structure_name(store_id)

    def _containing(self, unit: Vec3) -> list[Place]:
        return sorted(
            (
                place
                for place in self.world.places.values()
                if self.world.distance_m(unit, place.centre) <= place.radius_m
            ),
            key=lambda place: (place.radius_m, place.id),
        )

    def where(self, unit: Vec3) -> PlaceRef | None:
        """The smallest named place this point is in (the well rather than the castle town), if any."""
        inside = self._containing(unit)
        return PlaceRef(id=inside[0].id, name=inside[0].name) if inside else None

    def area(self, unit: Vec3) -> PlaceRef | None:
        """The largest named place this point is in (the castle town, a camp, a landmark), if any."""
        inside = self._containing(unit)
        return PlaceRef(id=inside[-1].id, name=inside[-1].name) if inside else None


_lock = threading.Lock()
_indexes: dict[str, PlaceIndex] = {}


def place_index(session: Session, generator: WorldGenerator) -> PlaceIndex:
    """The index over the current generator's world (built on first use, ~0.4 s)."""
    with _lock:
        index = _indexes.get(generator.version)
        if index is None:
            index = PlaceIndex(load_sim_world(session, generator))
            _indexes[generator.version] = index
        return index
