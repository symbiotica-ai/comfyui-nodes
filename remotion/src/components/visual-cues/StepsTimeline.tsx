// ABOUTME: Numbered vertical timeline with connector lines
// ABOUTME: Steps cascade in with staggered spring animation

import React from "react";
import { interpolate, spring, useVideoConfig } from "remotion";

interface Props {
  items: string[];
  activeStep?: number;
  localFrame: number;
  color: string;
  textShadow: string;
  fontFamily?: string;
}

export const StepsTimeline: React.FC<Props> = ({
  items,
  activeStep,
  localFrame,
  color,
  textShadow,
  fontFamily,
}) => {
  const { fps } = useVideoConfig();
  const font = fontFamily || "Inter, system-ui, sans-serif";
  const active = activeStep ?? items.length;

  return (
    <div style={{ width: "100%" }}>
      {items.map((item, i) => {
        const stepSpring = spring({
          frame: Math.max(0, localFrame - 5 - i * 8),
          fps,
          config: { damping: 14, stiffness: 300 },
        });
        const opacity = interpolate(stepSpring, [0, 1], [0, 1]);
        const translateX = interpolate(stepSpring, [0, 1], [-20, 0]);

        const isActive = i < active;
        const isLast = i === items.length - 1;

        return (
          <div
            key={i}
            style={{
              display: "flex",
              gap: 12,
              opacity,
              transform: `translateX(${translateX}px)`,
            }}
          >
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                flexShrink: 0,
              }}
            >
              <div
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: "50%",
                  backgroundColor: isActive ? color : "rgba(255,255,255,0.15)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: font,
                  fontSize: 13,
                  fontWeight: 700,
                  color: isActive ? "#FFFFFF" : "rgba(255,255,255,0.5)",
                }}
              >
                {i + 1}
              </div>
              {!isLast && (
                <div
                  style={{
                    width: 2,
                    height: 20,
                    backgroundColor: isActive ? color + "60" : "rgba(255,255,255,0.1)",
                  }}
                />
              )}
            </div>

            <div
              style={{
                fontFamily: font,
                fontSize: 16,
                color: isActive ? "rgba(255,255,255,0.9)" : "rgba(255,255,255,0.5)",
                lineHeight: 1.4,
                paddingTop: 4,
                paddingBottom: isLast ? 0 : 16,
                textShadow,
              }}
            >
              {item}
            </div>
          </div>
        );
      })}
    </div>
  );
};
