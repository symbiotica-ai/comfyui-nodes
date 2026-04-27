// ABOUTME: Horizontal fill bar with animated percentage label
// ABOUTME: Bar fills with smooth spring, shimmer effect on idle

import React from "react";
import { Easing, interpolate, spring, useVideoConfig } from "remotion";
import { parseNumericValue } from "./StatValue";

interface Props {
  value: string;
  title: string;
  localFrame: number;
  color: string;
  textShadow: string;
  fontFamily?: string;
}

export const ProgressBar: React.FC<Props> = ({
  value,
  title,
  localFrame,
  color,
  textShadow,
  fontFamily,
}) => {
  const { fps } = useVideoConfig();
  const { num } = parseNumericValue(value);
  const targetPercent = Math.min(100, Math.max(0, num));

  const fillSpring = spring({
    frame: localFrame,
    fps,
    config: { damping: 20, stiffness: 120 },
  });
  const fillWidth = interpolate(fillSpring, [0, 1], [0, targetPercent]);

  const counterProgress = Easing.out(Easing.cubic)(
    Math.min(1, Math.max(0, localFrame / 24))
  );
  const displayNum = Math.round(targetPercent * counterProgress);

  const font = fontFamily || "Inter, system-ui, sans-serif";

  return (
    <div style={{ width: "100%" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 8,
          fontFamily: font,
          fontSize: 16,
          color: "rgba(255, 255, 255, 0.9)",
          textShadow,
        }}
      >
        <span>{title}</span>
        <span style={{ color, fontWeight: 700 }}>{displayNum}%</span>
      </div>
      <div
        style={{
          width: "100%",
          height: 8,
          backgroundColor: "rgba(255, 255, 255, 0.1)",
          borderRadius: 4,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${fillWidth}%`,
            height: "100%",
            backgroundColor: color,
            borderRadius: 4,
            position: "relative",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent)",
              transform: `translateX(${((localFrame % 60) / 60) * 200 - 100}%)`,
            }}
          />
        </div>
      </div>
    </div>
  );
};
