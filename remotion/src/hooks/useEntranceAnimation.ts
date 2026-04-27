// ABOUTME: Shared entrance animation hook producing transform, opacity, and clipPath
// ABOUTME: Supports slide-reveal, scale-bounce, wipe, fade-slide (Phase 1) + 6 new types (Phase 2)

import { Easing, interpolate, spring } from "remotion";
import type { EntranceType, CuePosition } from "../types";

interface EntranceResult {
  transform: string;
  opacity: number;
  clipPath?: string;
  /** Extra CSS filter applied during entrance (used by blur-reveal) */
  filter?: string;
}

export function useEntranceAnimation(
  localFrame: number,
  fps: number,
  entranceType: EntranceType,
  springConfig: { damping: number; stiffness: number },
  position?: CuePosition
): EntranceResult {
  const entrSpring = spring({
    frame: localFrame,
    fps,
    config: springConfig,
  });

  let transform = "";
  let opacity = 1;
  let clipPath: string | undefined;
  let filter: string | undefined;

  switch (entranceType) {
    case "slide-reveal": {
      const slideFrom = position === "left" ? -400 : 400;
      const tx = interpolate(entrSpring, [0, 1], [slideFrom, 0]);
      transform = `translateX(${tx}px)`;
      opacity = interpolate(entrSpring, [0, 1], [0, 1]);
      break;
    }
    case "scale-bounce": {
      const s = interpolate(entrSpring, [0, 1], [1.3, 1.0]);
      transform = `scale(${s})`;
      opacity = interpolate(entrSpring, [0, 1], [0, 1]);
      break;
    }
    case "wipe": {
      const wipeProgress = interpolate(entrSpring, [0, 1], [100, 0]);
      clipPath = `inset(0 ${wipeProgress}% 0 0)`;
      opacity = 1;
      break;
    }
    case "fade-slide": {
      const ty = interpolate(entrSpring, [0, 1], [10, 0]);
      transform = `translateY(${ty}px)`;
      opacity = interpolate(entrSpring, [0, 1], [0, 1]);
      break;
    }
    case "blur-reveal": {
      const blur = interpolate(entrSpring, [0, 1], [20, 0]);
      filter = `blur(${blur}px)`;
      opacity = interpolate(entrSpring, [0, 1], [0, 1]);
      break;
    }
    case "flicker": {
      // Neon tube ignite: rapid opacity flicker then solid
      const flickerPhase = Math.min(localFrame / 12, 1);
      if (flickerPhase < 1) {
        const flick = Math.sin(localFrame * 8) * 0.5 + 0.5;
        opacity = flick * flickerPhase;
      } else {
        opacity = 1;
      }
      break;
    }
    case "clip-reveal": {
      // Expand from center vertically + horizontally
      const progress = interpolate(entrSpring, [0, 1], [50, 0]);
      clipPath = `inset(${progress}% ${progress}% ${progress}% ${progress}%)`;
      break;
    }
    case "slam-in": {
      // Fast overshoot scale entrance
      const slamSpring = spring({
        frame: localFrame,
        fps,
        config: { damping: 6, stiffness: 400 },
      });
      const s = interpolate(slamSpring, [0, 1], [2.5, 1.0]);
      transform = `scale(${s})`;
      opacity = interpolate(
        localFrame,
        [0, 3],
        [0, 1],
        { extrapolateRight: "clamp" }
      );
      break;
    }
    case "pop-in": {
      // Bouncy scale from zero
      const popSpring = spring({
        frame: localFrame,
        fps,
        config: { damping: 6, stiffness: 300 },
      });
      const s = interpolate(popSpring, [0, 1], [0, 1]);
      transform = `scale(${s})`;
      break;
    }
    case "typewriter": {
      // Simple fade-in for container; actual typewriter effect is in text components
      opacity = interpolate(
        localFrame,
        [0, 6],
        [0, 1],
        { extrapolateRight: "clamp" }
      );
      break;
    }
  }

  return { transform, opacity, clipPath, filter };
}
