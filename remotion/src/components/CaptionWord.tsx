// ABOUTME: Single word component with animation-aware rendering
// ABOUTME: Supports Pop, Bounce, Slam, Karaoke, Glow, Rise animation presets

import React from "react";
import {
  interpolate,
  interpolateColors,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { AnimationPreset, CaptionTemplate } from "../types";

interface Props {
  word: string;
  isActive: boolean;
  activeStartFrame: number | null;
  wordStart: number;
  wordEnd: number;
  wordIndex: number;
  chunkStartFrame: number;
  animation: AnimationPreset;
  template: CaptionTemplate;
  fontSize: number;
  fontColor: string;
  highlightColor: string;
}

export const CaptionWord: React.FC<Props> = ({
  word,
  isActive,
  activeStartFrame,
  wordStart,
  wordEnd,
  wordIndex,
  chunkStartFrame,
  animation,
  template,
  fontSize,
  fontColor,
  highlightColor,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  let scale = 1;
  let color = fontColor;
  let translateY = 0;
  let wordOpacity = 1;
  const extraStyle: React.CSSProperties = {};

  // --- Rise: staggered entrance per word (independent of activation) ---
  if (animation === "Rise") {
    const staggerDelay = wordIndex * 3;
    const riseFrame = Math.max(0, frame - chunkStartFrame - staggerDelay);
    const riseSpring = spring({
      frame: riseFrame,
      fps,
      config: { damping: 14, stiffness: 160 },
    });
    translateY = interpolate(riseSpring, [0, 1], [25, 0]);
    wordOpacity = interpolate(riseSpring, [0, 1], [0, 1]);
  }

  // --- Karaoke: gradient fill (bypasses normal isActive logic) ---
  if (animation === "Karaoke") {
    const startFrame = Math.round(wordStart * fps);
    const endFrame = Math.round(wordEnd * fps);
    const progress = interpolate(frame, [startFrame, endFrame], [0, 100], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    extraStyle.background = `linear-gradient(to right, ${highlightColor} ${progress}%, ${fontColor} ${progress}%)`;
    extraStyle.WebkitBackgroundClip = "text";
    extraStyle.WebkitTextFillColor = "transparent";
    extraStyle.backgroundClip = "text";
  } else if (isActive && activeStartFrame !== null) {
    // --- All other animations: spring-based activation ---
    const framesSince = frame - activeStartFrame;

    switch (animation) {
      case "Bounce": {
        const val = spring({
          frame: framesSince,
          fps,
          config: { damping: 8, stiffness: 250 },
        });
        translateY += interpolate(val, [0, 0.5, 1], [-18, 4, 0]);
        scale = interpolate(val, [0, 1], [0.8, 1.0]);
        color = interpolateColors(Math.min(val, 1), [0, 1], [
          fontColor,
          highlightColor,
        ]);
        break;
      }

      case "Slam": {
        const val = spring({
          frame: framesSince,
          fps,
          config: { damping: 10, stiffness: 350 },
        });
        scale = interpolate(val, [0, 1], [1.8, 1.0]);
        color = interpolateColors(Math.min(val, 1), [0, 1], [
          fontColor,
          highlightColor,
        ]);
        break;
      }

      case "Glow": {
        const val = spring({
          frame: framesSince,
          fps,
          config: { damping: 12, stiffness: 180 },
        });
        scale = interpolate(val, [0, 1], [1.0, 1.08]);
        color = interpolateColors(Math.min(val, 1), [0, 1], [
          fontColor,
          highlightColor,
        ]);
        const intensity = Math.min(val, 1);
        const r1 = 20 * intensity;
        const r2 = 40 * intensity;
        const baseShadow =
          template.textShadow !== "none" ? template.textShadow + ", " : "";
        extraStyle.textShadow = `${baseShadow}0 0 ${r1}px ${highlightColor}, 0 0 ${r2}px ${highlightColor}80`;
        break;
      }

      case "Rise": {
        const val = spring({
          frame: framesSince,
          fps,
          config: { damping: 14, stiffness: 160 },
        });
        scale = interpolate(val, [0, 1], [0.95, 1.0]);
        color = interpolateColors(Math.min(val, 1), [0, 1], [
          fontColor,
          highlightColor,
        ]);
        break;
      }

      case "Pop":
      default: {
        const val = spring({
          frame: framesSince,
          fps,
          config: {
            damping: template.wordSpring.damping,
            stiffness: template.wordSpring.stiffness,
          },
        });
        scale = interpolate(val, [0, 1], [0.85, 1]);
        color = interpolateColors(Math.min(val, 1), [0, 1], [
          fontColor,
          highlightColor,
        ]);
        break;
      }
    }
  }

  const displayWord = template.uppercase ? word.toUpperCase() : word;

  return (
    <span
      style={{
        display: "inline-block",
        fontFamily: template.fontFamily,
        fontWeight: template.fontWeight,
        fontSize,
        color,
        textShadow: template.textShadow,
        transform: `translateY(${translateY}px) scale(${scale})`,
        opacity: wordOpacity,
        marginRight: fontSize * 0.25,
        whiteSpace: "pre",
        ...extraStyle,
      }}
    >
      {displayWord}
    </span>
  );
};
