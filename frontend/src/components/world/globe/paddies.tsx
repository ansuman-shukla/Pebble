import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo } from 'react';
import { Color, type Group, InstancedMesh, Matrix4, type Mesh } from 'three';

import { kindModel } from '@/components/world/kind-parts';
import { assetBaseY, PROPS } from '@/lib/world/assets';
import type { LocalMapping } from '@/lib/world/local-mapping';
import type { NodeStages } from '@/lib/world/node-stages';
import {
  PADDY_STAGES,
  type PaddyField,
  type PaddyStage,
  paddyStage,
  TILE_SHAPES,
  type TileShape,
} from '@/lib/world/paddies';
import {
  createAsset,
  type RicePaddyOptions,
} from '@/vendor/polyfork/rice-paddy.mjs';

/*
 * The town's rice paddies drawn by their live stage (10 §1.4, §5.2): every tile of a paddy shows the paddy's stage
 * from the feed (NodeStages), built from Polyfork's parametric paddy tile with the season that IS that growth, and
 * shaped so a paddy is one basin with a bund round its rim only. One instanced mesh per stage and tile shape, so
 * the six paddies draw in at most a dozen calls (usually three to six: only the stages showing draw).
 *
 * The kit's crop is a 12 cm tile's: the stand is drawn `growth` times as tall (rice stands knee high when green,
 * higher when ripe), and once the stand closes its shade colours the water between the hills, so a green or a gold
 * paddy reads as one from any height.
 */

interface StageLook {
  options: RicePaddyOptions;
  /** Height factor of the crop over the kit's. */
  growth: number;
}

/** The kit's crop colours (its defaults): the vertices `growth` stretches. */
const CROP_COLOURS = ['#5C8F4E', '#8C6A2F', '#D9A441', '#D9C89A'];

/** The tile's season (its growth), the crop's height and the water seen under the stand, per stage. */
const STAGE_LOOKS: Record<PaddyStage, StageLook> = {
  seedlings: { options: { season: 'spring' }, growth: 1.5 },
  green: { options: { season: 'summer', water: '#3F5A3A' }, growth: 4 },
  gold: { options: { season: 'autumn', water: '#6A5A2E' }, growth: 4.5 },
  stubble: { options: { season: 'autumn', harvested: true }, growth: 1.5 },
};
/** The tile's bunds for each shape (`one-side` bunds its north edge, `corner` north and west). */
const SHAPE_BUNDS: Record<TileShape, RicePaddyOptions['bund']> = {
  open: 'none',
  side: 'one-side',
  corner: 'corner',
};

const lookKey = (stage: PaddyStage, shape: TileShape) => `${stage}:${shape}`;

const crop = CROP_COLOURS.map((hex) => {
  const { r, g, b } = new Color(hex);
  return [r, g, b].map(Math.fround);
});

/** Stretches the crop's vertices (by their colour) `factor` times up from the floor they stand on. */
function grow(mesh: Mesh, factor: number) {
  const position = mesh.geometry.getAttribute('position');
  const colour = mesh.geometry.getAttribute('color');
  const plant: number[] = [];
  for (let i = 0; i < position.count; i++) {
    const rgb = [colour.getX(i), colour.getY(i), colour.getZ(i)];
    if (crop.some((c) => c.every((value, k) => value === rgb[k])))
      plant.push(i);
  }
  const floor = Math.min(...plant.map((i) => position.getY(i)));
  for (const i of plant)
    position.setY(i, floor + (position.getY(i) - floor) * factor);
  position.needsUpdate = true;
  mesh.geometry.computeVertexNormals();
  mesh.geometry.computeBoundingBox();
  mesh.geometry.computeBoundingSphere();
}

/** One scene per look for the page's lifetime, so kindModel builds (and caches) its parts once. */
const scenes = new Map<string, Group>();
function tileScene(stage: PaddyStage, shape: TileShape) {
  const key = lookKey(stage, shape);
  let scene = scenes.get(key);
  if (!scene) {
    const { options, growth } = STAGE_LOOKS[stage];
    scene = createAsset({
      ...options,
      bund: SHAPE_BUNDS[shape],
      basins: 'one',
    });
    scene.traverse((object) => {
      if ((object as Mesh).isMesh) grow(object as Mesh, growth);
    });
    scenes.set(key, scene);
  }
  return scene;
}

declare global {
  interface Window {
    /** Test hook: the stage each paddy is drawn at, and the instances each look draws. */
    __pebblePaddies?: {
      drawn: () => Record<string, PaddyStage>;
      looks: () => { look: string; count: number }[];
    };
  }
}

/** The paddies' instanced looks and which stage each paddy shows. */
class PaddyLayer {
  readonly meshes = new Map<string, InstancedMesh>();
  private readonly placed: Matrix4[][];
  private readonly shown = new Map<string, PaddyStage>();
  private readonly ids: Set<string>;
  /** The stages' version last followed (-1: never drawn). */
  private seen = -1;

  constructor(
    private readonly fields: readonly PaddyField[],
    mapping: LocalMapping,
  ) {
    this.ids = new Set(fields.map((field) => field.id));
    const id = PROPS.rice_paddy;
    const baseY = assetBaseY(id);
    const capacity = new Map<TileShape, number>(
      TILE_SHAPES.map((shape) => [
        shape,
        fields.reduce(
          (sum, field) =>
            sum + field.tiles.filter((tile) => tile.shape === shape).length,
          0,
        ),
      ]),
    );
    for (const stage of PADDY_STAGES)
      for (const shape of TILE_SHAPES) {
        const [part, ...rest] = kindModel(tileScene(stage, shape), id).parts;
        if (!part || rest.length > 0)
          throw new Error('a paddy tile is one vertex-coloured part');
        const mesh = new InstancedMesh(
          part.geometry,
          part.material,
          Math.max(1, capacity.get(shape)!),
        );
        if (part.depthMaterial) mesh.customDepthMaterial = part.depthMaterial;
        mesh.name = `rice_paddy:${lookKey(stage, shape)}`;
        mesh.receiveShadow = true;
        mesh.count = 0;
        mesh.visible = false;
        this.meshes.set(lookKey(stage, shape), mesh);
      }
    this.placed = fields.map((field) =>
      field.tiles.map((tile) =>
        mapping.matrix(tile.x, baseY, tile.z, tile.yaw, new Matrix4()),
      ),
    );
  }

  /** Redraws when a paddy's stage changed since the last look (the first look draws every paddy). */
  follow(stages: NodeStages) {
    if (this.seen === stages.version) return;
    const changed = this.seen < 0 ? null : stages.changedSince(this.seen);
    this.seen = stages.version;
    if (changed !== null && !changed.some((node) => this.ids.has(node))) return;
    this.draw((paddy) => paddyStage(stages.state(paddy)?.stage));
  }

  /** Lays every paddy's tiles at the stage `stageOf` gives it. */
  private draw(stageOf: (paddy: string) => PaddyStage) {
    const counts = new Map<string, number>();
    this.fields.forEach((field, index) => {
      const stage = stageOf(field.id);
      this.shown.set(field.id, stage);
      field.tiles.forEach((tile, slot) => {
        const key = lookKey(stage, tile.shape);
        const count = counts.get(key) ?? 0;
        this.meshes.get(key)!.setMatrixAt(count, this.placed[index][slot]);
        counts.set(key, count + 1);
      });
    });
    for (const [key, mesh] of this.meshes) {
      mesh.count = counts.get(key) ?? 0;
      mesh.visible = mesh.count > 0;
      mesh.instanceMatrix.needsUpdate = true;
      mesh.computeBoundingSphere();
    }
  }

  drawn() {
    return Object.fromEntries(this.shown);
  }

  looks() {
    return [...this.meshes].map(([look, mesh]) => ({
      look,
      count: mesh.count,
    }));
  }

  dispose() {
    // the geometry and material belong to the shared model (kind-parts); only the instance buffers are ours
    for (const mesh of this.meshes.values()) mesh.dispose();
  }
}

export function GlobePaddies({
  fields,
  mapping,
  stages,
}: {
  fields: readonly PaddyField[];
  mapping: LocalMapping;
  stages: NodeStages;
}) {
  const layer = useMemo(
    () => new PaddyLayer(fields, mapping),
    [fields, mapping],
  );
  useEffect(() => () => layer.dispose(), [layer]);
  useEffect(() => {
    window.__pebblePaddies = {
      drawn: () => layer.drawn(),
      looks: () => layer.looks(),
    };
    return () => {
      delete window.__pebblePaddies;
    };
  }, [layer]);

  useFrame(() => layer.follow(stages));

  return (
    <>
      {[...layer.meshes.values()].map((mesh) => (
        <primitive key={mesh.uuid} object={mesh} />
      ))}
    </>
  );
}
