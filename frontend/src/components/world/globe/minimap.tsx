import { type RefObject, useEffect, useMemo, useRef, useState } from 'react';
import { Vector3 } from 'three';

import type { GoToSite } from './globe-drop';
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
  type MapPoint,
  mapPixelOf,
  mapPoint,
  METRES_PER_PX,
  REGION_COLORS,
} from '@/lib/world/minimap';

/*
 * The minimap (10-world-v1 §5.4): a 2D map of the site nearest the camera, 1 px = 2 m, north up. The ground is
 * coloured by biome, the town adds its water and building footprints; on top, the camera's spot, fires (orange),
 * animals (predators red) and every citizen by group (those elsewhere on the map's edge, toward where they are).
 * A click goes there. Roads, fields, hotspot outlines and nodes join as the world view carries them.
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

/** The site whose anchor is nearest to where the camera looks. */
function nearestSite(sites: GoToSite[], focus: Vector3) {
  const here = scratch.copy(focus).normalize();
  let best = sites[0];
  let bestAngle = Infinity;
  for (const site of sites) {
    const angle = site.mapping.toWorld(0, 0, 0, new Vector3()).angleTo(here);
    if (angle < bestAngle) {
      bestAngle = angle;
      best = site;
    }
  }
  return best;
}

/** The map's ground: biomes, then the town's water and footprints. */
function drawGround(
  context: CanvasRenderingContext2D,
  site: GoToSite,
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
  sites,
  terrain,
  biomeNames,
  town,
  citizens,
  animals,
  fires,
  views,
  focusRef,
  onGo,
}: {
  sites: GoToSite[];
  terrain: GlobeTerrain;
  biomeNames: string[];
  town: MinimapTown;
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
  // the first draw moves it to the site nearest the camera
  const [site, setSite] = useState(sites[0]);
  const [dots, setDots] = useState<Dot[]>([]);
  const ground = useMemo(() => {
    const layer = document.createElement('canvas');
    layer.width = layer.height = MAP_PX;
    const context = layer.getContext('2d');
    if (context) drawGround(context, site, terrain, biomeNames, town);
    return layer;
  }, [site, terrain, biomeNames, town]);

  useEffect(() => {
    const draw = () => {
      const next = nearestSite(sites, focusRef.current);
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
          .multiplyScalar(terrain.globe.radius);
      context.drawImage(ground, 0, 0);
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
  }, [sites, site, ground, citizens, animals, fires, views, focusRef, terrain]);

  return (
    <section
      role="region"
      aria-label="Minimap"
      data-minimap-site={site.id}
      className="flex flex-col gap-1 rounded-lg bg-white/90 p-1 text-xs shadow-lg"
    >
      <span className="px-1 font-medium">{site.name}</span>
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
