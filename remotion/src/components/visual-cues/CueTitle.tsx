// ABOUTME: Title text renderer with staggered reveal and template-driven styling
// ABOUTME: Extracted from VisualCue.tsx — handles font, alignment, and typewriter effect

import React from "react";
import { interpolate, spring, useVideoConfig } from "remotion";
import type { VisualCueTemplate, EntranceType } from "../../types";

interface Props {
  title: string;
  localFrame: number;
  template: VisualCueTemplate;
  cueScale: number;
  cardWidth: number;
  cueX: number;
  textShadow?: string;
}

export const CueTitle: React.FC<Props> = ({
  title,
  localFrame,
  template,
  cueScale,
  cardWidth,
  cueX,
  textShadow: textShadowOverride,
}) => {
  const { fps } = useVideoConfig();
  const titleSize = Math.round(template.titleSize * cueScale);
  const contentDelay = template.entranceType === "slide-reveal" ? 3 : 0;

  const titleSpring = spring({
    frame: Math.max(0, localFrame - 5 - contentDelay * 2),
    fps,
    config: template.entranceSpring,
  });
  const titleReveal = interpolate(titleSpring, [0, 1], [0, 1]);

  // Typewriter: show characters progressively
  const displayTitle =
    template.entranceType === "typewriter"
      ? title.slice(0, Math.floor(interpolate(
          Math.min(localFrame, title.length * 2 + 10),
          [0, title.length * 2 + 10],
          [0, title.length],
          { extrapolateRight: "clamp" }
        )))
      : title;

  const fontFamily = template.fontFamily || "Inter, system-ui, sans-serif";

  return (
    <div
      style={{
        opacity: titleReveal,
        color: "#FFFFFF",
        fontFamily,
        fontWeight: template.titleWeight,
        fontSize: titleSize,
        textAlign: template.layout === "bar" ? "left" : "center",
        lineHeight: 1.3,
        maxWidth: template.layout === "bar" ? undefined : cardWidth - 56,
        textShadow: textShadowOverride ?? template.textShadow,
        textTransform: template.uppercase ? "uppercase" : undefined,
        letterSpacing: template.uppercase ? "0.05em" : undefined,
      }}
    >
      {displayTitle}
    </div>
  );
};
