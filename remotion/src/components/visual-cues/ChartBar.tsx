// ABOUTME: Animated bar chart with staggered spring fills
// ABOUTME: Supports 3-5 bars with labels and values

import React from "react";
import { interpolate, spring, useVideoConfig } from "remotion";
import type { ChartDataPoint } from "../../types";

interface Props {
  data: ChartDataPoint[];
  localFrame: number;
  color: string;
  textShadow: string;
  fontFamily?: string;
}

export const ChartBar: React.FC<Props> = ({
  data,
  localFrame,
  color,
  textShadow,
  fontFamily,
}) => {
  const { fps } = useVideoConfig();
  const font = fontFamily || "Inter, system-ui, sans-serif";
  const maxVal = Math.max(...data.map((d) => d.value), 1);

  return (
    <div style={{ width: "100%", display: "flex", gap: 8, alignItems: "flex-end" }}>
      {data.map((d, i) => {
        const barSpring = spring({
          frame: Math.max(0, localFrame - 5 - i * 6),
          fps,
          config: { damping: 15, stiffness: 200 },
        });
        const barHeight = interpolate(
          barSpring,
          [0, 1],
          [0, (d.value / maxVal) * 80]
        );
        const opacity = interpolate(barSpring, [0, 1], [0, 1]);
        const barColor = d.color || color;

        return (
          <div
            key={i}
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 4,
              opacity,
            }}
          >
            <div
              style={{
                fontFamily: font,
                fontSize: 12,
                fontWeight: 700,
                color: barColor,
                textShadow,
              }}
            >
              {Math.round(d.value * barSpring)}
            </div>
            <div
              style={{
                width: "100%",
                height: barHeight,
                backgroundColor: barColor,
                borderRadius: 4,
                minHeight: 4,
              }}
            />
            <div
              style={{
                fontFamily: font,
                fontSize: 11,
                color: "rgba(255, 255, 255, 0.6)",
                textAlign: "center",
                textShadow,
                lineHeight: 1.2,
              }}
            >
              {d.label}
            </div>
          </div>
        );
      })}
    </div>
  );
};
