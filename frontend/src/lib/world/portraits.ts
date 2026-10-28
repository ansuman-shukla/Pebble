import {
  Box3,
  DirectionalLight,
  HemisphereLight,
  type Mesh,
  PerspectiveCamera,
  Scene,
  SRGBColorSpace,
  Vector3,
  WebGLRenderer,
} from 'three';

import { CITIZEN_LOOKS } from '@/lib/world/citizen-looks';
import { animateHumanoid } from '@/lib/world/humanoid-clips';
import { createCharacter } from '@/vendor/polyfork/humanoid.mjs';

/*
 * Head-and-shoulders portraits of the citizens' looks, rendered once per look into a PNG data URL by one shared
 * offscreen renderer (a page full of people would otherwise need a WebGL context each). The character stands in
 * the first frame of its Idle clip, facing the camera (+z).
 */

const SIZE = 192;
let renderer: WebGLRenderer | null = null;
const portraits = new Map<string, Promise<string>>();

function sharedRenderer(): WebGLRenderer {
  if (!renderer) {
    renderer = new WebGLRenderer({
      canvas: document.createElement('canvas'),
      antialias: true,
      alpha: true,
      preserveDrawingBuffer: true,
    });
    renderer.setSize(SIZE, SIZE, false);
    renderer.outputColorSpace = SRGBColorSpace;
  }
  return renderer;
}

async function render(lookId: string): Promise<string> {
  const look = CITIZEN_LOOKS.find((candidate) => candidate.id === lookId);
  if (!look) throw new Error(`no citizen look "${lookId}"`);
  const character = createCharacter(look.config);
  const animation = await animateHumanoid(character, ['Idle']);
  animation.play('Idle');
  animation.update(0);
  character.updateMatrixWorld(true);

  const box = new Box3().setFromObject(character);
  const height = box.max.y - box.min.y;
  const head = new Vector3(0, box.max.y - height * 0.13, 0);
  const camera = new PerspectiveCamera(30, 1, 0.05, 50);
  camera.position.set(height * 0.12, head.y + height * 0.02, height * 0.95);
  camera.lookAt(head.x, head.y - height * 0.05, head.z);

  const scene = new Scene();
  scene.add(new HemisphereLight('#ffffff', '#8a7a5a', 2));
  const sun = new DirectionalLight('#ffffff', 2.2);
  sun.position.set(2, 4, 5);
  scene.add(sun, character);

  const target = sharedRenderer();
  target.render(scene, camera);
  const url = target.domElement.toDataURL('image/png');
  character.traverse((object) => (object as Mesh).geometry?.dispose());
  return url;
}

/** The look's portrait as a data URL (rendered on first use, then cached). */
export function portraitUrl(lookId: string): Promise<string> {
  let portrait = portraits.get(lookId);
  if (!portrait) {
    portrait = render(lookId);
    portraits.set(lookId, portrait);
    portrait.catch(() => portraits.delete(lookId)); // try again next time
  }
  return portrait;
}
