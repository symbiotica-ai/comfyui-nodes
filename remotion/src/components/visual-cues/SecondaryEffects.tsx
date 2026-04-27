// ABOUTME: Renders secondary motion effects (shimmer, border-trace, particle-trail)
// ABOUTME: Positioned absolutely within CueContainer, purely decorative overlays

import React from "react";
import { useCurrentFrame } from "remotion";
import { useSecondaryMotion } from "../../hooks/useSecondaryMotion";
import type { SecondaryMotion } from "../../types";

interface Props {
  motion: SecondaryMotion | undefined;
  localFrame: number;
  color: string;
  borderRadius: number;
  width: number;
  height?: number;
}

export const SecondaryEffects: React.FC<Props> = ({
  motion,
  localFrame,
  color,
  borderRadius,
  width,
}) => {
  const result = useSecondaryMotion(localFrame, motion);

  if (result.type === "none") return null;

  if (result.type === "shimmer" && result.shimmerPosition !== undefined) {
    return (
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius,
          overflow: "hidden",
          pointerEvents: "none",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: `linear-gradient(
              110deg,
              transparent ${result.shimmerPosition - 30}%,
              rgba(255,255,255,0.08) ${result.shimmerPosition - 10}%,
              rgba(255,255,255,0.15) ${result.shimmerPosition}%,
              rgba(255,255,255,0.08) ${result.shimmerPosition + 10}%,
              transparent ${result.shimmerPosition + 30}%
            )`,
          }}
        />
      </div>
    );
  }

  if (result.type === "border-trace" && result.traceProgress !== undefined) {
    const r = borderRadius;
    const w = width;
    const h = 120; // approximate card height
    const perimeter = 2 * (w + h) - 8 * r + 2 * Math.PI * r;
    const dashLength = perimeter * result.traceProgress;

    return (
      <svg
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          pointerEvents: "none",
          overflow: "visible",
        }}
      >
        <rect
          x="0.5"
          y="0.5"
          rx={r}
          ry={r}
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          strokeDasharray={`${dashLength} ${perimeter}`}
          strokeDashoffset="0"
          opacity="0.6"
          style={{ width: "calc(100% - 1px)", height: "calc(100% - 1px)" }}
        />
      </svg>
    );
  }

  if (result.type === "particle-trail" && result.particles) {
    return (
      <div
        style={{
          position: "absolute",
          inset: 0,
          overflow: "hidden",
          borderRadius,
          pointerEvents: "none",
        }}
      >
        {result.particles.map((p, i) => (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${p.x}%`,
              top: `${p.y}%`,
              width: p.size,
              height: p.size,
              borderRadius: "50%",
              backgroundColor: color,
              opacity: p.opacity,
            }}
          />
        ))}
      </div>
    );
  }

  return null;
};
