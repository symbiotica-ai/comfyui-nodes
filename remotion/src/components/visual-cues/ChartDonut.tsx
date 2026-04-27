// ABOUTME: Animated donut chart with SVG arcs that grow sequentially
// ABOUTME: Shows data distribution with colored segments and center label

import React from "react";
import { interpolate, spring, useVideoConfig } from "remotion";
import type { ChartDataPoint } from "../../types";

interface Props {
  data: ChartDataPoint[];
  title: string;
  localFrame: number;
  color: string;
  textShadow: string;
  fontFamily?: string;
}

const DONUT_SIZE = 100;
const STROKE_WIDTH = 14;
const RADIUS = (DONUT_SIZE - STROKE_WIDTH) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const CENTER = DONUT_SIZE / 2;

const SEGMENT_COLORS = [
  "#4361EE", "#F7C948", "#22C55E", "#FF3366", "#A855F7",
];

export const ChartDonut: React.FC<Props> = ({
  data,
  title,
  localFrame,
  color,
  textShadow,
  fontFamily,
}) => {
  const { fps } = useVideoConfig();
  const font = fontFamily || "Inter, system-ui, sans-serif";
  const total = data.reduce((sum, d) => sum + d.value, 0) || 1;

  let cumulativeOffset = 0;
  const segments = data.map((d, i) => {
    const segSpring = spring({
      frame: Math.max(0, localFrame - 5 - i * 6),
      fps,
      config: { damping: 18, stiffness: 150 },
    });

    const fraction = d.value / total;
    const segmentLength = fraction * CIRCUMFERENCE;
    const animatedLength = segmentLength * segSpring;
    const offset = cumulativeOffset;
    cumulativeOffset += segmentLength;

    return {
      color: d.color || SEGMENT_COLORS[i % SEGMENT_COLORS.length],
      dasharray: `${animatedLength} ${CIRCUMFERENCE - animatedLength}`,
      dashoffset: -offset,
      label: d.label,
      opacity: interpolate(segSpring, [0, 1], [0, 1]),
    };
  });

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 12,
        width: "100%",
      }}
    >
      <div style={{ position: "relative", width: DONUT_SIZE, height: DONUT_SIZE }}>
        <svg
          width={DONUT_SIZE}
          height={DONUT_SIZE}
          viewBox={`0 0 ${DONUT_SIZE} ${DONUT_SIZE}`}
        >
          <circle
            cx={CENTER}
            cy={CENTER}
            r={RADIUS}
            fill="none"
            stroke="rgba(255,255,255,0.1)"
            strokeWidth={STROKE_WIDTH}
          />
          {segments.map((seg, i) => (
            <circle
              key={i}
              cx={CENTER}
              cy={CENTER}
              r={RADIUS}
              fill="none"
              stroke={seg.color}
              strokeWidth={STROKE_WIDTH}
              strokeDasharray={seg.dasharray}
              strokeDashoffset={seg.dashoffset}
              strokeLinecap="round"
              transform={`rotate(-90 ${CENTER} ${CENTER})`}
              opacity={seg.opacity}
            />
          ))}
        </svg>

        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: font,
            fontSize: 14,
            fontWeight: 700,
            color: "#FFFFFF",
            textShadow,
          }}
        >
          {title}
        </div>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
        {segments.map((seg, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              opacity: seg.opacity,
            }}
          >
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor: seg.color,
              }}
            />
            <span
              style={{
                fontFamily: font,
                fontSize: 11,
                color: "rgba(255, 255, 255, 0.7)",
                textShadow,
              }}
            >
              {data[i].label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};
