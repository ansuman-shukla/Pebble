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
  PROPS,
  type PropKind,
} from '@/lib/world/assets';
import { BIOME_PROPS, LANDMARK_KINDS } from '@/lib/world/biome-props';
import { CITIZEN_LOOKS, type Region } from '@/lib/world/citizen-looks';

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

// camera position + target per view
const VIEWS = {
  citizens: [0, 9, 13, 0, 0.6, 0],
  animals: [0, 6, 22, 0, 0.8, 11],
  all: [0, 10, 24, 0, 1, 5],
  'plants & rocks': [0, 25, 6, 0, 0, -40],
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

function PropModel({ kind }: { kind: PropKind }) {
  const id = PROPS[kind];
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
          <PropModel kind={kind} />
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
