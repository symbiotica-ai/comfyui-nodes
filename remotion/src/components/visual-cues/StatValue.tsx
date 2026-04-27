// ABOUTME: Animated numeric counter for stat cue type
// ABOUTME: Extracted from VisualCue.tsx — parses prefix/number/suffix and interpolates

import React from "react";
import { Easing } from "remotion";

interface Props {
  value: string;
  localFrame: number;
  color: string;
  fontSize: number;
  textShadow: string;
  fontFamily?: string;
}

export const parseNumericValue = (
  value: string
): { num: number; prefix: string; suffix: string } => {
  const match = value.match(/^([^0-9-]*)([-]?[\d.]+)(.*)$/);
  if (!match) return { num: 0, prefix: "", suffix: value };
  return { num: parseFloat(match[2]), prefix: match[1], suffix: match[3] };
};

export const StatValue: React.FC<Props> = ({
  value,
  localFrame,
  color,
  fontSize,
  textShadow,
  fontFamily,
}) => {
  const { num, prefix, suffix } = parseNumericValue(value);

  const counterFrames = 24;
  const rawProgress = Math.min(1, Math.max(0, localFrame / counterFrames));
  const progress = Easing.out(Easing.cubic)(rawProgress);

  const isInteger = Number.isInteger(num);
  const displayNum = isInteger
    ? Math.round(num * progress).toString()
    : (num * progress).toFixed(1);

  return (
    <div
      style={{
        color,
        fontFamily: fontFamily || "Inter, system-ui, sans-serif",
        fontWeight: 700,
        fontSize,
        textAlign: "center",
        lineHeight: 1.1,
        textShadow,
      }}
    >
      {prefix}
      {displayNum}
      {suffix}
    </div>
  );
};
