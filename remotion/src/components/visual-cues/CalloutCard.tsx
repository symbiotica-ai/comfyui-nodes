// ABOUTME: Larger card with description paragraph that fades in line-by-line
// ABOUTME: For expanded explanations, descriptions, and important callouts

import React from "react";
import { interpolate, spring, useVideoConfig } from "remotion";

interface Props {
  description: string;
  localFrame: number;
  textShadow: string;
  fontFamily?: string;
}

export const CalloutCard: React.FC<Props> = ({
  description,
  localFrame,
  textShadow,
  fontFamily,
}) => {
  const { fps } = useVideoConfig();
  const font = fontFamily || "Inter, system-ui, sans-serif";

  const lines = description.split(/(?<=[.!?])\s+/).filter(Boolean);

  return (
    <div style={{ width: "100%", marginTop: 4 }}>
      {lines.map((line, i) => {
        const lineSpring = spring({
          frame: Math.max(0, localFrame - 10 - i * 8),
          fps,
          config: { damping: 15, stiffness: 200 },
        });
        const opacity = interpolate(lineSpring, [0, 1], [0, 1]);
        const translateY = interpolate(lineSpring, [0, 1], [8, 0]);

        return (
          <div
            key={i}
            style={{
              opacity,
              transform: `translateY(${translateY}px)`,
              color: "rgba(255, 255, 255, 0.85)",
              fontFamily: font,
              fontWeight: 400,
              fontSize: 15,
              lineHeight: 1.5,
              marginBottom: 4,
              textShadow,
            }}
          >
            {line}
          </div>
        );
      })}
    </div>
  );
};
