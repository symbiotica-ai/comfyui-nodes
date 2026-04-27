// ABOUTME: Pull-quote with opening quotation mark and attribution
// ABOUTME: Text fades in word-by-word for dramatic effect

import React from "react";
import { interpolate, spring, useVideoConfig } from "remotion";

interface Props {
  text: string;
  attribution?: string;
  localFrame: number;
  color: string;
  textShadow: string;
  fontFamily?: string;
}

export const QuoteBlock: React.FC<Props> = ({
  text,
  attribution,
  localFrame,
  color,
  textShadow,
  fontFamily,
}) => {
  const { fps } = useVideoConfig();
  const font = fontFamily || "Inter, system-ui, sans-serif";
  const words = text.split(/\s+/);

  return (
    <div style={{ width: "100%" }}>
      <div
        style={{
          color,
          fontFamily: "Georgia, serif",
          fontSize: 64,
          lineHeight: 0.5,
          marginBottom: 12,
          opacity: 0.6,
        }}
      >
        {"\u201C"}
      </div>

      <div
        style={{
          fontFamily: font,
          fontSize: 18,
          fontWeight: 400,
          fontStyle: "italic",
          lineHeight: 1.6,
          color: "rgba(255, 255, 255, 0.9)",
          textShadow,
        }}
      >
        {words.map((word, i) => {
          const wordSpring = spring({
            frame: Math.max(0, localFrame - 5 - i * 3),
            fps,
            config: { damping: 20, stiffness: 200 },
          });
          const opacity = interpolate(wordSpring, [0, 1], [0, 1]);

          return (
            <span key={i} style={{ opacity }}>
              {word}{" "}
            </span>
          );
        })}
      </div>

      {attribution && (
        <div
          style={{
            marginTop: 12,
            fontFamily: font,
            fontSize: 14,
            color: "rgba(255, 255, 255, 0.5)",
            textShadow,
          }}
        >
          {"\u2014 "}
          {attribution}
        </div>
      )}
    </div>
  );
};
