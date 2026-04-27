// ABOUTME: Lucide icon renderer with entrance spring and optional background/glow
// ABOUTME: Extracted from VisualCue.tsx — handles icon styling per template config

import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { icons } from "lucide-react";
import type { VisualCueTemplate } from "../../types";

interface Props {
  name: string;
  color: string;
  localFrame: number;
  template: VisualCueTemplate;
  cueScale: number;
}

const LucideIcon: React.FC<{ name: string; size: number; color: string }> = ({
  name,
  size,
  color,
}) => {
  const pascalName = name
    .split("-")
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join("");
  const IconComponent = icons[pascalName as keyof typeof icons];
  if (!IconComponent) return null;
  return <IconComponent size={size} color={color} strokeWidth={1.5} />;
};

export { LucideIcon };

export const CueIcon: React.FC<Props> = ({
  name,
  color,
  localFrame,
  template,
  cueScale,
}) => {
  const { fps } = useVideoConfig();
  const iconSize = Math.round(48 * cueScale);

  const iconSpring = spring({
    frame: Math.max(0, localFrame - 5),
    fps,
    config: { damping: 8, stiffness: 500 },
  });
  const iconScale = interpolate(iconSpring, [0, 1], [0, 1]);

  if (template.iconBackground) {
    return (
      <div
        style={{
          transform: `scale(${iconScale})`,
          flexShrink: 0,
          width: iconSize + Math.round(24 * cueScale),
          height: iconSize + Math.round(24 * cueScale),
          borderRadius: "50%",
          backgroundColor: "rgba(255, 255, 255, 0.2)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <LucideIcon name={name} size={iconSize} color="#FFFFFF" />
      </div>
    );
  }

  if (template.iconGlow) {
    return (
      <div
        style={{
          transform: `scale(${iconScale})`,
          flexShrink: 0,
          filter: `drop-shadow(0 0 12px ${color}60)`,
        }}
      >
        <LucideIcon name={name} size={iconSize} color="#FFFFFF" />
      </div>
    );
  }

  return (
    <div style={{ transform: `scale(${iconScale})`, flexShrink: 0 }}>
      <LucideIcon name={name} size={iconSize} color="#FFFFFF" />
    </div>
  );
};
