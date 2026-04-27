// ABOUTME: Side-by-side A vs B comparison with animated bars
// ABOUTME: Left side enters first, right 8 frames later

import React from "react";
import { interpolate, spring, useVideoConfig } from "remotion";

interface Props {
  leftLabel: string;
  leftValue: number;
  rightLabel: string;
  rightValue: number;
  localFrame: number;
  color: string;
  textShadow: string;
  fontFamily?: string;
}

export const ComparisonCard: React.FC<Props> = ({
  leftLabel,
  leftValue,
  rightLabel,
  rightValue,
  localFrame,
  color,
  textShadow,
  fontFamily,
}) => {
  const { fps } = useVideoConfig();
  const maxVal = Math.max(leftValue, rightValue, 1);
  const font = fontFamily || "Inter, system-ui, sans-serif";

  const leftSpring = spring({
    frame: localFrame,
    fps,
    config: { damping: 18, stiffness: 150 },
  });
  const rightSpring = spring({
    frame: Math.max(0, localFrame - 8),
    fps,
    config: { damping: 18, stiffness: 150 },
  });

  const leftWidth = interpolate(leftSpring, [0, 1], [0, (leftValue / maxVal) * 100]);
  const rightWidth = interpolate(rightSpring, [0, 1], [0, (rightValue / maxVal) * 100]);

  const leftOpacity = interpolate(leftSpring, [0, 1], [0, 1]);
  const rightOpacity = interpolate(rightSpring, [0, 1], [0, 1]);

  const renderSide = (
    label: string,
    value: number,
    width: number,
    opacity: number,
    isRight: boolean
  ) => (
    <div style={{ flex: 1, opacity }}>
      <div
        style={{
          fontFamily: font,
          fontSize: 14,
          color: "rgba(255, 255, 255, 0.7)",
          marginBottom: 4,
          textShadow,
          textAlign: isRight ? "right" : "left",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: font,
          fontSize: 28,
          fontWeight: 700,
          color: "#FFFFFF",
          marginBottom: 8,
          textShadow,
          textAlign: isRight ? "right" : "left",
        }}
      >
        {Math.round(value * (opacity > 0.5 ? 1 : opacity * 2))}
      </div>
      <div
        style={{
          width: "100%",
          height: 6,
          backgroundColor: "rgba(255, 255, 255, 0.1)",
          borderRadius: 3,
          overflow: "hidden",
          display: "flex",
          justifyContent: isRight ? "flex-end" : "flex-start",
        }}
      >
        <div
          style={{
            width: `${width}%`,
            height: "100%",
            backgroundColor: isRight ? "rgba(255,255,255,0.4)" : color,
            borderRadius: 3,
          }}
        />
      </div>
    </div>
  );

  return (
    <div style={{ width: "100%", display: "flex", gap: 16, alignItems: "flex-start" }}>
      {renderSide(leftLabel, leftValue, leftWidth, leftOpacity, false)}
      <div
        style={{
          color: "rgba(255,255,255,0.3)",
          fontFamily: font,
          fontSize: 14,
          fontWeight: 700,
          alignSelf: "center",
          paddingTop: 20,
        }}
      >
        VS
      </div>
      {renderSide(rightLabel, rightValue, rightWidth, rightOpacity, true)}
    </div>
  );
};
