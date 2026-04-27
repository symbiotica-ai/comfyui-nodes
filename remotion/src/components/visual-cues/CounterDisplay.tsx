// ABOUTME: Big standalone number display (60px+) with animated counting
// ABOUTME: Uses smooth interpolation, optimized for large stat callouts

import React from "react";
import { Easing } from "remotion";
import { parseNumericValue } from "./StatValue";

interface Props {
  value: string;
  prefix?: string;
  suffix?: string;
  localFrame: number;
  color: string;
  textShadow: string;
  fontFamily?: string;
}

export const CounterDisplay: React.FC<Props> = ({
  value,
  prefix: explicitPrefix,
  suffix: explicitSuffix,
  localFrame,
  color,
  textShadow,
  fontFamily,
}) => {
  const { num, prefix: parsedPrefix, suffix: parsedSuffix } = parseNumericValue(value);
  const prefix = explicitPrefix ?? parsedPrefix;
  const suffix = explicitSuffix ?? parsedSuffix;
  const font = fontFamily || "Inter, system-ui, sans-serif";

  const counterFrames = 30;
  const rawProgress = Math.min(1, Math.max(0, localFrame / counterFrames));
  const progress = Easing.out(Easing.cubic)(rawProgress);

  const isInteger = Number.isInteger(num);
  const displayNum = isInteger
    ? Math.round(num * progress).toString()
    : (num * progress).toFixed(1);

  return (
    <div style={{ textAlign: "center" }}>
      <div
        style={{
          color,
          fontFamily: font,
          fontWeight: 800,
          fontSize: 64,
          lineHeight: 1,
          textShadow,
        }}
      >
        {prefix}
        {displayNum}
        {suffix}
      </div>
    </div>
  );
};
