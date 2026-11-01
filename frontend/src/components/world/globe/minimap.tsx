import { type RefObject, useEffect, useMemo, useRef, useState } from 'react';
import { Vector3 } from 'three';

import type { NpcViews } from './globe-npcs';
import type { TownPlacement, TownWater } from '@/lib/client/types.gen';
import type {
  LiveAnimal,
  LiveCitizen,
  LiveFire,
} from '@/lib/live/live-contract';
import type { GlobeTerrain } from '@/lib/world/globe';
import { biomeColor } from '@/lib/world/globe-mesh';
import {
  animalColor,
  FIRE_COLOR,
  MAP_PX,
  type MapArea,
  type MapNode,
  type MapPoint,
  mapPixelOf,
  mapPoint,
  type MapView,
  mapViewAt,
  METRES_PER_PX,
  nodeColor,
  REGION_COLORS,
} from '@/lib/world/minimap';
import type { NodeStages } from '@/lib/world/node-stages';

/*
 * The minimap (10-world-v1 §5.4): a 2D map of where the camera is (the site or hotspot it is in, else the wilds
 * around it, named by the biome), 1 px = 2 m, north up. The ground is coloured by biome, the town adds its water and
 * building footprints; on top, every node as a small square coloured by its stock (the scarcity view), the camera's
 * spot, fires (orange), animals (predators red) and every citizen by group (those elsewhere on the map's edge,
 * toward where they are). A click goes there. Roads, fields and hotspot outlines join as the world view carries them.
 */

/** How often the dots are redrawn (ms). */
const DRAW_MS = 250;
/** The ground is sampled every this many px. */
const GROUND_STEP_PX = 10;
const WATER_COLOR = '#3b82f6';
const FOOTPRINT_COLOR = '#57534e';

export interface MinimapTown {
  siteId: string;
  placements: TownPlacement[];
  water: TownWater[];
}

interface Dot {
  id: string;
  point: MapPoint;
}

const scratch = new Vector3();
/** Nodes are looked up this far (m) from the map's centre: its corners. */
const NODE_REACH = Math.SQRT2 * (MAP_PX / 2) * METRES_PER_PX;
const NODE_PX = 3;

/** The map's ground: biomes, then the town's water and footprints. */
function drawGround(
  context: CanvasRenderingContext2D,
  site: MapView,
  terrain: GlobeTerrain,
  biomeNames: string[],
  town: MinimapTown,
) {
  const point = new Vector3();
  for (let y = 0; y < MAP_PX; y += GROUND_STEP_PX)
    for (let x = 0; x < MAP_PX; x += GROUND_STEP_PX) {
      const local = mapPoint(x + GROUND_STEP_PX / 2, y + GROUND_STEP_PX / 2);
      site.mapping.toWorld(local.x, 0, local.z, point).normalize();
      context.fillStyle = biomeColor(biomeNames[terrain.biomeAt(point)]);
      context.fillRect(x, y, GROUND_STEP_PX, GROUND_STEP_PX);
    }
  if (site.id !== town.siteId) return;
  const toPx = (value: number) => value / METRES_PER_PX + MAP_PX / 2;
  context.fillStyle = WATER_COLOR;
  for (const water of town.water) {
    context.beginPath();
    for (const ring of [water.polygon, ...(water.holes ?? [])]) {
      ring.forEach(([x, z], index) =>
        index === 0
          ? context.moveTo(toPx(x), toPx(z))
          : context.lineTo(toPx(x), toPx(z)),
      );
      context.closePath();
    }
    context.fill('evenodd');
  }
  context.fillStyle = FOOTPRINT_COLOR;
  for (const placement of town.placements) {
    if (placement.walk !== 'solid') continue;
    const turned =
      placement.rotation_deg === 90 || placement.rotation_deg === 270;
    const width =
      (turned ? placement.footprint.z : placement.footprint.x) / METRES_PER_PX;
    const depth =
      (turned ? placement.footprint.x : placement.footprint.z) / METRES_PER_PX;
    context.fillRect(
      toPx(placement.x) - width / 2,
      toPx(placement.z) - depth / 2,
      width,
      depth,
    );
  }
}

function drawDot(
  context: CanvasRenderingContext2D,
  { x, y, edge }: MapPoint,
  color: string,
  size: number,
) {
  context.beginPath();
  context.arc(x, y, size, 0, Math.PI * 2);
  if (edge) {
    context.strokeStyle = color;
    context.lineWidth = 1.5;
    context.stroke();
  } else {
    context.fillStyle = color;
    context.fill();
  }
}

export function Minimap({
  areas,
  terrain,
  biomeNames,
  town,
  nodesNear,
  stages,
  citizens,
  animals,
  fires,
  views,
  focusRef,
  onGo,
}: {
  /** Where the map centres while the camera is in one: sites first, then hotspots. */
  areas: MapArea[];
  terrain: GlobeTerrain;
  biomeNames: string[];
  town: MinimapTown;
  /** The nodes within some metres of a direction (looked up once per map). */
  nodesNear: (direction: Vector3, metres: number) => MapNode[];
  /** How full each node is. */
  stages: NodeStages;
  citizens: LiveCitizen[];
  animals: LiveAnimal[];
  fires: LiveFire[];
  /** What is drawn of each citizen (smoother than the feed's tick positions). */
  views: NpcViews;
  focusRef: RefObject<Vector3>;
  /** Go to a world direction (a click on the map). */
  onGo: (direction: Vector3) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const radius = terrain.globe.radius;
  // the first draw moves it to where the camera is
  const [site, setSite] = useState<MapView>(areas[0]);
  const [dots, setDots] = useState<Dot[]>([]);
  const [drawnNodes, setDrawnNodes] = useState({ all: 0, scarce: 0 });
  const ground = useMemo(() => {
    const layer = document.createElement('canvas');
    layer.width = layer.height = MAP_PX;
    const context = layer.getContext('2d');
    if (context) drawGround(context, site, terrain, biomeNames, town);
    return layer;
  }, [site, terrain, biomeNames, town]);
  const { mapping } = site;
  const nodes = useMemo(
    () =>
      nodesNear(
        mapping.toWorld(0, 0, 0, new Vector3()).normalize(),
        NODE_REACH,
      ),
    [mapping, nodesNear],
  );

  useEffect(() => {
    const draw = () => {
      const next = mapViewAt(
        focusRef.current,
        areas,
        radius,
        biomeNames[terrain.biomeAt(scratch.copy(focusRef.current).normalize())],
        site,
      );
      if (next !== site) {
        setSite(next);
        return;
      }
      const context = canvas.current?.getContext('2d');
      if (!context) return;
      const pixel = (world: Vector3) => mapPixelOf(site.mapping, world);
      const unit = (position: { unit: number[] }) =>
        scratch
          .set(position.unit[0], position.unit[1], position.unit[2])
          .multiplyScalar(radius);
      context.drawImage(ground, 0, 0);
      let shown = 0;
      let scarce = 0;
      for (const node of nodes) {
        const point = pixel(
          scratch.copy(node.direction).multiplyScalar(radius),
        );
        if (point.edge) continue;
        const fill = stages.state(node.id)?.fill ?? 1;
        context.fillStyle = nodeColor(fill);
        context.fillRect(
          point.x - NODE_PX / 2,
          point.y - NODE_PX / 2,
          NODE_PX,
          NODE_PX,
        );
        shown += 1;
        if (fill < 1) scarce += 1;
      }
      setDrawnNodes((current) =>
        current.all === shown && current.scarce === scarce
          ? current
          : { all: shown, scarce },
      );
      for (const fire of fires) {
        const point = pixel(unit(fire.position));
        if (!point.edge) drawDot(context, point, FIRE_COLOR, 3);
      }
      for (const animal of animals) {
        const point = pixel(unit(animal.position));
        if (!point.edge) drawDot(context, point, animalColor(animal.kind), 2);
      }
      const drawn: Dot[] = citizens.map((citizen) => {
        const view = views.get(citizen.id);
        const point = pixel(view ? view.pose.position : unit(citizen.position));
        drawDot(context, point, REGION_COLORS[citizen.region], 3);
        return { id: citizen.id, point };
      });
      const camera = pixel(focusRef.current);
      context.strokeStyle = '#000';
      context.lineWidth = 1;
      context.strokeRect(camera.x - 4, camera.y - 4, 8, 8);
      setDots(drawn);
    };
    draw();
    const timer = window.setInterval(draw, DRAW_MS);
    return () => window.clearInterval(timer);
  }, [
    areas,
    site,
    ground,
    nodes,
    stages,
    citizens,
    animals,
    fires,
    views,
    focusRef,
    terrain,
    biomeNames,
    radius,
  ]);

  return (
    <section
      role="region"
      aria-label="Minimap"
      data-minimap-site={site.id}
      data-minimap-nodes={drawnNodes.all}
      data-minimap-scarce={drawnNodes.scarce}
      className="flex flex-col gap-1 rounded-lg bg-white/90 p-1 text-xs shadow-lg"
    >
      <span className="px-1 font-medium" data-testid="minimap-title">
        {site.name}
      </span>
      <canvas
        ref={canvas}
        width={MAP_PX}
        height={MAP_PX}
        className="cursor-crosshair rounded"
        onClick={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          const local = mapPoint(
            ((event.clientX - box.left) / box.width) * MAP_PX,
            ((event.clientY - box.top) / box.height) * MAP_PX,
          );
          onGo(
            site.mapping
              .toWorld(local.x, 0, local.z, new Vector3())
              .normalize(),
          );
        }}
      />
      <div hidden data-testid="minimap-dots">
        {dots.map(({ id, point }) => (
          <span
            key={id}
            data-minimap-dot={id}
            data-x={point.x.toFixed(1)}
            data-y={point.y.toFixed(1)}
            data-edge={point.edge}
          />
        ))}
      </div>
    </section>
  );
}
