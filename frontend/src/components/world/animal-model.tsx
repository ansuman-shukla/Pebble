import { useGLTF } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { type RefObject, useEffect, useMemo, useRef } from 'react';
import {
  type AnimationAction,
  AnimationMixer,
  type Group,
  Matrix4,
} from 'three';
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js';

import { MAX_FRAME, smoothing } from '@/components/world/player/motion';
import {
  type AnimalClip,
  type AnimalDrive,
  type AnimalLayer,
  bodyMatrix,
  blendPose,
  layerPose,
  newDrive,
  paceOf,
  poseBones,
  rigOf,
  strideSpeed,
  unbendBones,
} from '@/lib/live/animal-motion';
import { ANIMALS, type AnimalKind, assetUrl } from '@/lib/world/assets';
import { recolor } from '@/lib/world/recolor';

/*
 * One animal model: its baked clips paced to the ground it covers and the procedural layer of what it does on top
 * (`animal-motion.ts`). Live animals are driven frame by frame through `drive`; the gallery just names a clip.
 */

/** How fast a layer's pose eases into the next one (1/s of natural time). */
const BLEND_RATE = 10;
/** Clips cross-fade over this long (natural seconds). */
const FADE_S = 0.2;

/** Natural stride speeds (root units per second) of each asset's gait clips, measured once per asset. */
const STRIDES = new Map<string, Partial<Record<AnimalClip, number | null>>>();

type AnimalModelProps = {
  kind: AnimalKind;
  /** A fixed clip at its natural speed (the gallery); ignored with `driveRef`. */
  gait?: AnimalClip;
  /** Live: what to play, written by the caller every frame (the model writes back what it plays). */
  driveRef?: RefObject<AnimalDrive>;
};

export function AnimalModel({
  kind,
  gait = 'idle',
  driveRef,
}: AnimalModelProps) {
  const spec = ANIMALS[kind];
  const scale = spec.scale ?? 1;
  const { scene, animations } = useGLTF(assetUrl(spec.asset));
  const { model, rig, mixer, strides } = useMemo(() => {
    const copy = clone(scene);
    if (spec.recolor) recolor(copy, spec.recolor);
    const rigged = rigOf(copy);
    let measured = STRIDES.get(spec.asset);
    if (!measured) {
      measured = {};
      for (const clip of ['move', 'run'] as const) {
        const found = animations.find(({ name }) => name === spec[clip]);
        measured[clip] = found ? strideSpeed(rigged, found) : null;
      }
      STRIDES.set(spec.asset, measured);
    }
    return {
      model: copy,
      rig: rigged,
      mixer: new AnimationMixer(copy),
      strides: measured,
    };
  }, [scene, animations, spec]);
  const body = useRef<Group>(null);
  const playing = useRef<{ clip: AnimalClip; action: AnimationAction } | null>(
    null,
  );
  const layer = useRef<{ layer: AnimalLayer; clock: number }>({
    layer: 'none',
    clock: 0,
  });
  const ownRef = useRef<AnimalDrive>(newDrive());
  const matrix = useMemo(() => new Matrix4(), []);

  useEffect(() => () => void mixer.stopAllAction(), [mixer]);

  useFrame((_, frameDelta) => {
    if (!driveRef) ownRef.current.clip = gait;
    const wanted = driveRef ? driveRef.current : ownRef.current;
    const natural = Math.min(frameDelta, MAX_FRAME) * wanted.rate;
    const name = spec[wanted.clip];
    if (playing.current?.clip !== wanted.clip) {
      playing.current?.action.fadeOut(FADE_S);
      const action = mixer.clipAction(
        animations.find((clip) => clip.name === name) ?? animations[0],
      );
      action.reset().fadeIn(FADE_S).play();
      playing.current = { clip: wanted.clip, action };
      wanted.clipName = name;
    }
    const step = layer.current;
    if (step.layer !== wanted.layer) {
      step.layer = wanted.layer;
      step.clock = 0;
    }
    step.clock += natural;
    const target = layerPose(wanted.layer, step.clock);
    blendPose(wanted.pose, target, smoothing(BLEND_RATE, natural));
    const stride = strides[wanted.clip];
    wanted.pace =
      !driveRef || wanted.clip === 'idle'
        ? 1
        : paceOf(wanted.speed, stride == null ? null : stride * scale);
    playing.current.action.timeScale = wanted.pose.still ? 0 : wanted.pace;
    unbendBones(rig);
    mixer.update(natural);
    poseBones(rig, wanted.pose);
    if (!body.current) return;
    body.current.matrixWorldNeedsUpdate = true;
    bodyMatrix(
      wanted.pose,
      {
        halfWidth: rig.halfWidth * scale,
        centreY: rig.centreY * scale,
        hindZ: rig.hindZ * scale,
      },
      body.current.matrix,
    );
  });

  return (
    <group ref={body} matrixAutoUpdate={false} matrix={matrix}>
      <primitive object={model} scale={scale} />
    </group>
  );
}
