// ABOUTME: Secondary motion layer hook for shimmer, border-trace, and particle-trail effects
// ABOUTME: Returns render-ready style data consumed by SecondaryEffects component

import type { SecondaryMotion } from "../types";

interface SecondaryMotionResult {
  type: SecondaryMotion;
  /** Shimmer: diagonal gradient position 0-200% */
  shimmerPosition?: number;
  /** Border-trace: SVG path progress 0-1 */
  traceProgress?: number;
  /** Particle-trail: array of particle positions */
  particles?: Array<{ x: number; y: number; opacity: number; size: number }>;
}

export function useSecondaryMotion(
  localFrame: number,
  motion: SecondaryMotion | undefined
): SecondaryMotionResult {
  const type = motion ?? "none";

  if (type === "none") {
    return { type };
  }

  if (type === "shimmer") {
    // Diagonal gradient sweep cycling every ~120 frames
    const shimmerPosition = (localFrame % 120) / 120 * 200;
    return { type, shimmerPosition };
  }

  if (type === "border-trace") {
    // SVG path progress cycling every ~90 frames
    const traceProgress = Math.min(1, (localFrame % 90) / 60);
    return { type, traceProgress };
  }

  if (type === "particle-trail") {
    // Generate 5 drifting particles
    const particles = Array.from({ length: 5 }, (_, i) => {
      const seed = i * 73;
      const phase = (localFrame + seed) / 40;
      return {
        x: 50 + Math.sin(phase) * 40,
        y: 50 + Math.cos(phase * 0.7 + seed) * 30,
        opacity: 0.3 + Math.sin(phase * 2) * 0.2,
        size: 2 + Math.sin(phase + seed) * 1,
      };
    });
    return { type, particles };
  }

  return { type };
}
