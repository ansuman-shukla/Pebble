/** follow: third person behind the player; orbit: bird's-eye over the place; fly: free flight, player stays put. */
export type CameraMode = 'follow' | 'orbit' | 'fly';

export const CAMERA_MODES: CameraMode[] = ['follow', 'orbit', 'fly'];

export const nextCameraMode = (mode: CameraMode) =>
  CAMERA_MODES[(CAMERA_MODES.indexOf(mode) + 1) % CAMERA_MODES.length];
