// ABOUTME: Shared idle animation hook producing CSS transform string
// ABOUTME: Supports float, pulse, breathe, glow-pulse, wiggle, scan-line, none

import type { IdleAnimation } from "../types";

interface IdleResult {
  transform: string;
  /** Extra boxShadow modifier for glow-pulse */
  glowIntensity?: number;
  /** Vertical position 0-1 for scan-line overlay */
  scanLineY?: number;
}

export function useIdleAnimation(
  localFrame: number,
  idleAnimation: IdleAnimation
): IdleResult {
  let transform = "";
  let glowIntensity: number | undefined;
  let scanLineY: number | undefined;

  switch (idleAnimation) {
    case "float":
      transform = `translateY(${Math.sin(localFrame / 15) * 3}px)`;
      break;
    case "pulse":
      transform = `scale(${1 + Math.sin(localFrame / 20) * 0.015})`;
      break;
    case "breathe":
      // Imperceptible scale oscillation
      transform = `scale(${1 + Math.sin(localFrame / 30) * 0.008})`;
      break;
    case "glow-pulse":
      glowIntensity = 0.5 + Math.sin(localFrame / 18) * 0.3;
      break;
    case "wiggle":
      // Micro-rotation
      transform = `rotate(${Math.sin(localFrame / 10) * 1.5}deg)`;
      break;
    case "scan-line":
      // Position cycles 0→1 every ~90 frames
      scanLineY = (localFrame % 90) / 90;
      break;
    case "none":
      break;
  }

  return { transform, glowIntensity, scanLineY };
}
