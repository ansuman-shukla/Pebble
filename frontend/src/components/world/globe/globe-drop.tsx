import { useThree } from '@react-three/fiber';
import { type RefObject, useEffect } from 'react';
import { type Camera, Raycaster, Vector2, Vector3 } from 'three';

import { startFlight } from './camera-flight';
import type { GlobePlayerState, GlobeRig } from './globe-player';
import type { CameraMode } from '@/components/world/player/camera-mode';
import {
  type GlobeTerrain,
  latLonFromDirection,
  type SiteMapping,
  tangent,
  tangentFrame,
} from '@/lib/world/globe';
import { pickSurface } from '@/lib/world/globe-pick';
import type { GlobeWalk } from '@/lib/world/globe-walk';

/*
 * Dropping the player anywhere (Street View's pegman): a point picked on the screen is traced onto the
 * rendered planet; on land the player is put there, facing where the camera looked, and the camera flies down
 * into the follow view; water is refused. "Go to" drops the player at a named site.
 */

/** Where a drop put the player, or why it didn't. */
export type DropResult =
  | { ok: true; lat: number; lon: number; bearing: number }
  | { ok: false; reason: 'water' | 'miss' | 'loading' };

/** What lies under a client position: land to drop on, water, or nothing (space). */
export type DropTarget = 'land' | 'water' | null;

/** The page's handle on dropping (filled once the walk is ready). */
export interface DropApi {
  /** What a drop at a client (CSS pixel) position on the canvas would hit. */
  probe(clientX: number, clientY: number): DropTarget;
  /** Drops at the planet point under a client (CSS pixel) position on the canvas. */
  atScreen(clientX: number, clientY: number): DropResult;
  goTo(siteId: string): DropResult;
}

/** A site the "Go to" menu offers. */
export interface GoToSite {
  id: string;
  name: string;
  mapping: SiteMapping;
  /** A fixed spawn (the town's, by its main gate); without one a free spot near the anchor is found. */
  spawn: { position: Vector3; facing: Vector3 } | null;
}

/** Rings (metres from the anchor) searched for a free spot to stand at a site. */
const SITE_RINGS = [6, 8, 10, 12, 15, 18, 22, 26, 30];
const SITE_RING_POINTS = 16;
/** Ground probes for a drop start this high (above any walkable surface). */
const PROBE_FROM = 1000;

const raycaster = new Raycaster();
const pointer = new Vector2();

/** The bearing (degrees clockwise from north) of a tangent at a direction. */
function bearingOf(direction: Vector3, facing: Vector3) {
  const { east, north } = tangentFrame(direction);
  const degrees =
    (Math.atan2(facing.dot(east), facing.dot(north)) * 180) / Math.PI;
  return (degrees + 360) % 360;
}

/** Below this angle between the view ray and the ground the camera looks along the ground, not down on it. */
const STEEP_VIEW = Math.PI / 4;

/**
 * Which way to face after a drop: along the view ray when the camera looks across the ground, else (looking
 * down from above) the camera's screen-up, which is north in the orbit view.
 */
function viewFacing(camera: Camera, ray: Vector3, up: Vector3) {
  const across = Math.asin(Math.min(1, Math.abs(ray.dot(up)))) < STEEP_VIEW;
  const along = across
    ? ray.clone()
    : new Vector3(0, 1, 0).applyQuaternion(camera.quaternion);
  return tangent(along, up, tangentFrame(up).north);
}

/** A free spot on a ring around the site's anchor (south first), facing the anchor. */
function siteSpawn(walk: GlobeWalk, mapping: SiteMapping) {
  const anchor = mapping.toWorld(0, 0, 0, new Vector3()).normalize();
  for (const ring of SITE_RINGS) {
    for (let k = 0; k < SITE_RING_POINTS; k++) {
      const angle = (k / SITE_RING_POINTS) * Math.PI * 2;
      const position = mapping
        .toWorld(
          Math.sin(angle) * ring,
          0,
          Math.cos(angle) * ring,
          new Vector3(),
        )
        .normalize();
      if (!walk.isFree(position)) continue;
      const facing = tangent(anchor.clone().sub(position), position);
      return { position, facing };
    }
  }
  return null;
}

export function GlobeDrop({
  terrain,
  walkRef,
  playerRef,
  rigRef,
  dropRef,
  goTo,
  onCameraModeChange,
}: {
  terrain: GlobeTerrain;
  walkRef: RefObject<GlobeWalk | null>;
  playerRef: RefObject<GlobePlayerState>;
  rigRef: RefObject<GlobeRig>;
  dropRef: RefObject<DropApi | null>;
  goTo: GoToSite[];
  onCameraModeChange: (mode: CameraMode) => void;
}) {
  const camera = useThree((state) => state.camera);
  const canvas = useThree((state) => state.gl.domElement);

  useEffect(() => {
    const radius = terrain.globe.radius;

    /** Puts the player at a free spot (unit direction) facing a tangent, and flies the camera down to it. */
    function place(spot: Vector3, facing: Vector3): DropResult {
      const walk = walkRef.current;
      if (!walk) return { ok: false, reason: 'loading' };
      const player = playerRef.current;
      const rig = rigRef.current;
      player.ground = walk.groundAt(spot, PROBE_FROM);
      player.position.copy(spot).multiplyScalar(radius + player.ground);
      player.facing.copy(
        tangent(facing.clone(), spot, tangentFrame(spot).north),
      );
      rig.heading.copy(player.facing);
      startFlight(rig, camera);
      onCameraModeChange('follow');
      const { lat, lon } = latLonFromDirection(spot);
      return { ok: true, lat, lon, bearing: bearingOf(spot, player.facing) };
    }

    function dropAt(direction: Vector3, facing: Vector3): DropResult {
      const walk = walkRef.current;
      if (!walk) return { ok: false, reason: 'loading' };
      const spot = walk.dropSpot(direction);
      return spot ? place(spot, facing) : { ok: false, reason: 'water' };
    }

    /** The planet point under a client position (unit direction), or null. */
    function pick(walk: GlobeWalk, clientX: number, clientY: number) {
      const rect = canvas.getBoundingClientRect();
      pointer.set(
        ((clientX - rect.left) / rect.width) * 2 - 1,
        -((clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const hit = pickSurface(
        raycaster.ray.origin,
        raycaster.ray.direction,
        radius,
        walk.floorAt,
      );
      return hit && hit.normalize();
    }

    dropRef.current = {
      probe(clientX, clientY) {
        const walk = walkRef.current;
        const direction = walk && pick(walk, clientX, clientY);
        if (!walk || !direction) return null;
        return walk.isDry(direction) ? 'land' : 'water';
      },
      atScreen(clientX, clientY) {
        const walk = walkRef.current;
        if (!walk) return { ok: false, reason: 'loading' };
        const direction = pick(walk, clientX, clientY);
        if (!direction) return { ok: false, reason: 'miss' };
        return dropAt(
          direction,
          viewFacing(camera, raycaster.ray.direction, direction),
        );
      },
      goTo(siteId) {
        const walk = walkRef.current;
        if (!walk) return { ok: false, reason: 'loading' };
        const site = goTo.find((candidate) => candidate.id === siteId);
        if (!site) throw new Error(`unknown site ${siteId}`);
        const spawn = site.spawn
          ? {
              position: site.spawn.position.clone().normalize(),
              facing: site.spawn.facing,
            }
          : siteSpawn(walk, site.mapping);
        if (!spawn) return { ok: false, reason: 'miss' };
        return place(spawn.position, spawn.facing);
      },
    };
    return () => {
      dropRef.current = null;
    };
  }, [
    terrain,
    walkRef,
    playerRef,
    rigRef,
    dropRef,
    goTo,
    camera,
    canvas,
    onCameraModeChange,
  ]);

  return null;
}
