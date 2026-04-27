// ABOUTME: Shared exit animation hook producing opacity, scale, clipPath, and filter
// ABOUTME: Supports fade, scale-down, wipe-out, blur-out, flicker-out

import { Easing, interpolate } from "remotion";
import type { ExitType, EntranceType } from "../types";

const aeEase = Easing.bezier(0.76, 0, 0.24, 1);

interface ExitResult {
  opacity: number;
  scale: number;
  clipPath?: string;
  filter?: string;
}

/**
 * Resolve which exit type to use. If the template specifies an explicit exitType
 * use that; otherwise fall back to matching behaviour from the original code.
 */
function resolveExitType(
  exitType: ExitType | undefined,
  entranceType: EntranceType
): ExitType {
  if (exitType) return exitType;
  if (entranceType === "wipe") return "wipe-out";
  if (entranceType === "scale-bounce" || entranceType === "pop-in") return "scale-down";
  return "fade";
}

export function useExitAnimation(
  remainingFrames: number,
  exitFrames: number,
  exitType: ExitType | undefined,
  entranceType: EntranceType
): ExitResult {
  let opacity = 1;
  let scale = 1;
  let clipPath: string | undefined;
  let filter: string | undefined;

  if (remainingFrames >= exitFrames) {
    return { opacity, scale, clipPath, filter };
  }

  const rawP = interpolate(
    remainingFrames,
    [0, exitFrames],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const eased = aeEase(rawP);
  const resolved = resolveExitType(exitType, entranceType);

  switch (resolved) {
    case "wipe-out": {
      const wipeOut = interpolate(eased, [0, 1], [100, 0]);
      clipPath = `inset(0 0 0 ${wipeOut}%)`;
      break;
    }
    case "scale-down": {
      opacity = eased;
      scale = interpolate(eased, [0, 1], [0.8, 1.0]);
      break;
    }
    case "fade": {
      opacity = eased;
      scale = interpolate(eased, [0, 1], [0.92, 1.0]);
      break;
    }
    case "blur-out": {
      const blur = interpolate(eased, [0, 1], [20, 0]);
      filter = `blur(${blur}px)`;
      opacity = eased;
      break;
    }
    case "flicker-out": {
      const flickerPhase = 1 - rawP;
      if (flickerPhase > 0.2) {
        const flick = Math.sin(remainingFrames * 8) * 0.5 + 0.5;
        opacity = flick * flickerPhase;
      } else {
        opacity = 0;
      }
      break;
    }
  }

  return { opacity, scale, clipPath, filter };
}
