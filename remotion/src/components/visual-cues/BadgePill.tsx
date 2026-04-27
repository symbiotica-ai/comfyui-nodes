// ABOUTME: Small compact pill tag with quick pop-in animation
// ABOUTME: Designed for lightweight labels, multiple simultaneous badges

import React from "react";
import { interpolate, spring, useVideoConfig } from "remotion";

interface Props {
  title: string;
  localFrame: number;
  color: string;
  fontFamily?: string;
}

export const BadgePill: React.FC<Props> = ({
  title,
  localFrame,
  color,
  fontFamily,
}) => {
  const { fps } = useVideoConfig();
  const font = fontFamily || "Inter, system-ui, sans-serif";

  const popSpring = spring({
    frame: localFrame,
    fps,
    config: { damping: 8, stiffness: 400 },
  });
  const scale = interpolate(popSpring, [0, 1], [0, 1]);

  return (
    <div
      style={{
        transform: `scale(${scale})`,
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        backgroundColor: color,
        borderRadius: 100,
        padding: "6px 14px",
      }}
    >
      <span
        style={{
          color: "#FFFFFF",
          fontFamily: font,
          fontWeight: 600,
          fontSize: 14,
          lineHeight: 1,
          whiteSpace: "nowrap",
        }}
      >
        {title}
      </span>
    </div>
  );
};
