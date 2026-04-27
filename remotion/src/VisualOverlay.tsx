// ABOUTME: Remotion composition for animated infographic overlays on transparent background
// ABOUTME: Renders visual cues (12 types, 10 styles) at their scheduled times with responsive scaling

import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { VisualOverlayProps } from "./types";
import { VISUAL_TEMPLATES } from "./visual-templates";
import { VisualCue } from "./components/VisualCue";

export const VisualOverlay: React.FC<VisualOverlayProps> = ({ cues, defaultStyle }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const currentTime = frame / fps;

  const activeCues = cues.filter(
    (cue) => currentTime >= cue.startTime && currentTime <= cue.endTime
  );

  return (
    <AbsoluteFill style={{ backgroundColor: "transparent" }}>
      {activeCues.map((cue, i) => {
        const style = cue.style ?? defaultStyle ?? "cinematic";
        const template = VISUAL_TEMPLATES[style];
        const color = cue.color ?? "#00D4FF";

        return (
          <VisualCue
            key={`${cue.startTime}-${cue.position}-${i}`}
            cue={cue}
            template={template}
            color={color}
          />
        );
      })}
    </AbsoluteFill>
  );
};
