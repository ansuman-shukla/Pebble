import { CameraControls, useGLTF } from '@react-three/drei';
import { Canvas } from '@react-three/fiber';
import {
  memo,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js';

import { AnimalModel } from '@/components/world/animal-model';
import { CitizenModel } from '@/components/world/citizen-model';
import { Label, LabelOverlay, LabelProjector } from '@/components/world/labels';
import { useLabelStore } from '@/hooks/use-label-store';
import type { LabelStore } from '@/lib/world/label-store';
import { Button } from '@/components/ui/button';
import {
  ANIMALS,
  type AnimalKind,
  assetBaseY,
  assetSize,
  assetUrl,
  HAND_PROPS,
  type HandPropKind,
  PROPS,
  type PropKind,
} from '@/lib/world/assets';
import { BIOME_PROPS, LANDMARK_KINDS } from '@/lib/world/biome-props';
import {
  CITIZEN_LOOKS,
  type CitizenLook,
  type Region,
} from '@/lib/world/citizen-looks';
import { KIT_LOOKS, type KitLookId } from '@/lib/world/kit-looks';

const ROW_Z: Record<Region, number> = { town: -4.5, band_a: 0, band_b: 4.5 };
const CITIZEN_SPACING = 2;
const ANIMAL_SPACING = 3.6;
const ANIMALS_PER_ROW = 8;
const ANIMAL_KINDS = Object.keys(ANIMALS) as AnimalKind[];

// every kind the globe scatters or builds landmarks from, shortest first so tall trees stand at the back
const WILD_KINDS = [
  ...new Set<PropKind>([
    ...Object.values(BIOME_PROPS).flatMap((entries) =>
      entries.map((entry) => entry.kind),
    ),
    ...LANDMARK_KINDS,
  ]),
].sort((a, b) => assetSize(PROPS[a]).y - assetSize(PROPS[b]).y);
const WILD_SPACING = 6;
const WILD_ROW_DEPTH = 7;
const WILD_PER_ROW = 8;
const WILD_FRONT_Z = -26;
const WILD_ROWS = Math.ceil(WILD_KINDS.length / WILD_PER_ROW);

// every other kind (town, camps, world v1 stores and markers) on shelves packed by real size, shortest in front
const SHELF_KINDS = (Object.keys(PROPS) as PropKind[])
  .filter((kind) => !WILD_KINDS.includes(kind))
  .sort((a, b) => assetSize(PROPS[a]).y - assetSize(PROPS[b]).y);
const SHELF_WIDTH = 48;
const SHELF_GAP = 1.5;
const SHELF_FRONT_Z = 70;

interface ShelfSpot {
  kind: PropKind;
  x: number;
  z: number;
}

/** Packs kinds left to right into rows of SHELF_WIDTH by real size, each row behind the previous one. */
function packShelves(kinds: PropKind[], frontZ: number): ShelfSpot[] {
  const rows: PropKind[][] = [[]];
  let used = 0;
  for (const kind of kinds) {
    const width = assetSize(PROPS[kind]).x + SHELF_GAP;
    if (used + width > SHELF_WIDTH && rows.at(-1)!.length) {
      rows.push([]);
      used = 0;
    }
    rows.at(-1)!.push(kind);
    used += width;
  }
  const spots: ShelfSpot[] = [];
  let z = frontZ;
  let previousDepth = 0;
  for (const row of rows) {
    const sizes = row.map((kind) => assetSize(PROPS[kind]));
    const depth = Math.max(...sizes.map((size) => size.z));
    z -= previousDepth / 2 + SHELF_GAP + depth / 2;
    previousDepth = depth;
    let x = -sizes.reduce((sum, size) => sum + size.x + SHELF_GAP, 0) / 2;
    row.forEach((kind, index) => {
      spots.push({ kind, x: x + sizes[index].x / 2, z });
      x += sizes[index].x + SHELF_GAP;
    });
  }
  return spots;
}

const SHELF_SPOTS = packShelves(SHELF_KINDS, SHELF_FRONT_Z);
const SHELF_BACK_Z = Math.min(...SHELF_SPOTS.map((spot) => spot.z)) - 12;

// in front of the shelves: hand props with a model, then kit looks and a farmer holding each wardrobe-only prop
const HAND_KINDS = Object.keys(HAND_PROPS) as HandPropKind[];
const HAND_MODELS = HAND_KINDS.flatMap((kind) => {
  const prop = HAND_PROPS[kind];
  return 'asset' in prop ? [{ kind, asset: prop.asset }] : [];
});
const HAND_Z = SHELF_FRONT_Z + 2;
const HAND_SPACING = 1.6;
const KIT_Z = SHELF_FRONT_Z + 6;
const KIT_GALLERY_LOOKS: CitizenLook[] = [
  ...(Object.keys(KIT_LOOKS) as KitLookId[]).map((id) => ({
    id: `kit-${id}`,
    region: 'town' as const,
    role: id.replaceAll('_', ' '),
    config: KIT_LOOKS[id],
  })),
  ...HAND_KINDS.flatMap((kind) => {
    const prop = HAND_PROPS[kind];
    if (!('wardrobe' in prop)) return [];
    return [
      {
        id: `hand-${kind}`,
        region: 'town' as const,
        role: kind.replaceAll('_', ' '),
        config: {
          ...KIT_LOOKS.farmer,
          wear: { ...KIT_LOOKS.farmer.wear, righthand: prop.wardrobe },
        },
      },
    ];
  }),
];

// camera position + target per view
const VIEWS = {
  citizens: [0, 9, 13, 0, 0.6, 0],
  animals: [0, 6, 22, 0, 0.8, 11],
  all: [0, 10, 24, 0, 1, 5],
  'plants & rocks': [0, 25, 6, 0, 0, -40],
  'props & tools': [0, 26, SHELF_FRONT_Z + 30, 0, 0, SHELF_FRONT_Z - 12],
} as const;
type View = keyof typeof VIEWS;

function GalleryCamera({ view }: { view: View }) {
  const controls = useRef<CameraControls>(null);
  const first = useRef(true);
  useEffect(() => {
    const [px, py, pz, tx, ty, tz] = VIEWS[view];
    controls.current?.setLookAt(px, py, pz, tx, ty, tz, !first.current);
    first.current = false;
  }, [view]);
  return <CameraControls ref={controls} maxPolarAngle={Math.PI / 2.05} />;
}

function animalLabelHeight(kind: AnimalKind) {
  const { asset, scale = 1 } = ANIMALS[kind];
  return assetSize(asset).y * scale + 0.3;
}

function rowX(index: number, count: number, spacing: number) {
  return (index - (count - 1) / 2) * spacing;
}

function AssetModel({ id }: { id: string }) {
  const { scene } = useGLTF(assetUrl(id));
  // SkeletonUtils keeps skinned parts (the reed bed's and dune grass's wind-swayed blades) bound to their bones
  const model = useMemo(() => clone(scene), [scene]);
  return <primitive object={model} position-y={assetBaseY(id)} />;
}

function WildProps({ labels }: { labels: LabelStore }) {
  return (
    <>
      <mesh
        rotation-x={-Math.PI / 2}
        position-z={WILD_FRONT_Z - ((WILD_ROWS - 1) * WILD_ROW_DEPTH) / 2}
        receiveShadow
      >
        <planeGeometry
          args={[
            WILD_PER_ROW * WILD_SPACING + 8,
            WILD_ROWS * WILD_ROW_DEPTH + 6,
          ]}
        />
        <meshStandardMaterial color="#b5b48a" />
      </mesh>
      {WILD_KINDS.map((kind, index) => (
        <group
          key={kind}
          position={[
            rowX(index % WILD_PER_ROW, WILD_PER_ROW, WILD_SPACING),
            0,
            WILD_FRONT_Z - Math.floor(index / WILD_PER_ROW) * WILD_ROW_DEPTH,
          ]}
        >
          <AssetModel id={PROPS[kind]} />
          <Label
            store={labels}
            id={`prop-${kind}`}
            text={kind.replaceAll('_', ' ')}
            height={assetSize(PROPS[kind]).y + 0.3}
          />
        </group>
      ))}
    </>
  );
}

function ShelfProps({ labels }: { labels: LabelStore }) {
  const depth = SHELF_FRONT_Z + 10 - SHELF_BACK_Z;
  return (
    <>
      <mesh
        rotation-x={-Math.PI / 2}
        position-z={SHELF_BACK_Z + depth / 2}
        receiveShadow
      >
        <planeGeometry args={[SHELF_WIDTH + 10, depth]} />
        <meshStandardMaterial color="#b9b29a" />
      </mesh>
      {SHELF_SPOTS.map(({ kind, x, z }) => (
        <group key={kind} position={[x, 0, z]}>
          <AssetModel id={PROPS[kind]} />
          <Label
            store={labels}
            id={`prop-${kind}`}
            text={kind.replaceAll('_', ' ')}
            height={assetSize(PROPS[kind]).y + 0.3}
          />
        </group>
      ))}
      {HAND_MODELS.map(({ kind, asset }, index) => (
        <group
          key={kind}
          position={[rowX(index, HAND_MODELS.length, HAND_SPACING), 0, HAND_Z]}
        >
          <AssetModel id={asset} />
          <Label
            store={labels}
            id={`hand-${kind}`}
            text={kind.replaceAll('_', ' ')}
            height={assetSize(asset).y + 0.3}
          />
        </group>
      ))}
      {KIT_GALLERY_LOOKS.map((look, index) => (
        <group
          key={look.id}
          position={[
            rowX(index, KIT_GALLERY_LOOKS.length, CITIZEN_SPACING),
            0,
            KIT_Z,
          ]}
        >
          <CitizenModel look={look} motion="Idle" />
          <Label store={labels} id={look.id} text={look.role} height={2.15} />
        </group>
      ))}
    </>
  );
}

type GallerySceneProps = {
  labels: LabelStore;
  moving: boolean;
  view: View;
  onCitizenReady: (id: string) => void;
};

// Memoized so the ready counter re-rendering the page never re-renders the whole scene.
const GalleryScene = memo(function GalleryScene({
  labels,
  moving,
  view,
  onCitizenReady,
}: GallerySceneProps) {
  return (
    <Canvas
      flat
      shadows
      camera={{ fov: 40 }}
      gl={{ preserveDrawingBuffer: true }}
    >
      <color attach="background" args={['#cfe3ef']} />
      <hemisphereLight args={['#ffffff', '#8a7a5a', 1.6]} />
      <directionalLight position={[8, 14, 10]} intensity={2.2} castShadow />
      <mesh rotation-x={-Math.PI / 2} receiveShadow>
        <planeGeometry args={[80, 40]} />
        <meshStandardMaterial color="#9fb37a" />
      </mesh>
      {(['town', 'band_a', 'band_b'] as Region[]).map((region) => {
        const looks = CITIZEN_LOOKS.filter((look) => look.region === region);
        return looks.map((look, index) => (
          <group
            key={look.id}
            position={[
              rowX(index, looks.length, CITIZEN_SPACING),
              0,
              ROW_Z[region],
            ]}
          >
            <CitizenModel
              look={look}
              motion={moving ? 'Walk' : 'Idle'}
              onReady={onCitizenReady}
            />
            <Label store={labels} id={look.id} text={look.role} height={2.15} />
          </group>
        ));
      })}
      <Suspense fallback={null}>
        {ANIMAL_KINDS.map((kind, index) => (
          <group
            key={kind}
            position={[
              rowX(index % ANIMALS_PER_ROW, ANIMALS_PER_ROW, ANIMAL_SPACING),
              0,
              9 + Math.floor(index / ANIMALS_PER_ROW) * 4,
            ]}
          >
            <AnimalModel kind={kind} gait={moving ? 'move' : 'idle'} />
            <Label
              store={labels}
              id={kind}
              text={kind.replace('_', ' ')}
              height={animalLabelHeight(kind)}
            />
          </group>
        ))}
      </Suspense>
      {view === 'plants & rocks' && (
        <Suspense fallback={null}>
          <WildProps labels={labels} />
        </Suspense>
      )}
      {view === 'props & tools' && (
        <Suspense fallback={null}>
          <ShelfProps labels={labels} />
        </Suspense>
      )}
      <GalleryCamera view={view} />
      <LabelProjector store={labels} />
    </Canvas>
  );
});

export function GalleryPage() {
  const [moving, setMoving] = useState(false);
  const [view, setView] = useState<View>('citizens');
  const labels = useLabelStore();
  const [ready, setReady] = useState<Set<string>>(new Set());
  const markReady = useCallback(
    (id: string) => setReady((previous) => new Set(previous).add(id)),
    [],
  );

  return (
    <div
      className="relative h-full w-full"
      data-testid="gallery"
      data-citizens-ready={ready.size}
    >
      <GalleryScene
        labels={labels}
        moving={moving}
        view={view}
        onCitizenReady={markReady}
      />
      <LabelOverlay store={labels} />
      <div className="absolute top-3 left-3 flex items-center gap-2 rounded-lg bg-white/80 p-2 text-sm shadow">
        <span>
          {ready.size}/{CITIZEN_LOOKS.length} citizens, {ANIMAL_KINDS.length}{' '}
          animals, {WILD_KINDS.length} plants &amp; rocks
        </span>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setMoving((m) => !m)}
        >
          {moving ? 'Stand still' : 'Walk'}
        </Button>
        {(Object.keys(VIEWS) as View[]).map((option) => (
          <Button
            key={option}
            size="sm"
            variant="ghost"
            onClick={() => setView(option)}
          >
            {option}
          </Button>
        ))}
      </div>
    </div>
  );
}
