// ABOUTME: Positioning and animation wrapper for all visual cue types
// ABOUTME: Handles entrance/exit/idle animations, accent bars, underlines, secondary effects, and layout modes

import React from "react";
import {
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { useEntranceAnimation } from "../../hooks/useEntranceAnimation";
import { useExitAnimation } from "../../hooks/useExitAnimation";
import { useIdleAnimation } from "../../hooks/useIdleAnimation";
import { SecondaryEffects } from "./SecondaryEffects";
import type { VisualCue as VisualCueType, VisualCueTemplate } from "../../types";

/** Darken a hex color by mixing with black */
export const darkenColor = (hex: string, amount: number): string => {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const dr = Math.round(r * (1 - amount));
  const dg = Math.round(g * (1 - amount));
  const db = Math.round(b * (1 - amount));
  return `#${dr.toString(16).padStart(2, "0")}${dg.toString(16).padStart(2, "0")}${db.toString(16).padStart(2, "0")}`;
};

/** Resolve color placeholders in any template string */
const resolveColorPlaceholders = (str: string, color: string): string => {
  return str
    .replace(/\{color\}/g, color)
    .replace(/\{colorDark\}/g, darkenColor(color, 0.4))
    .replace(/\{colorShadow\}/g, color + "40");
};

export { resolveColorPlaceholders };
export const resolveBackground = resolveColorPlaceholders;
export const resolveBoxShadow = resolveColorPlaceholders;

interface Props {
  cue: VisualCueType;
  template: VisualCueTemplate;
  color: string;
  children: React.ReactNode;
  barFooter?: React.ReactNode;
}

export const CueContainer: React.FC<Props> = ({
  cue,
  template,
  color,
  children,
  barFooter,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const startFrame = Math.round(cue.startTime * fps);
  const endFrame = Math.round(cue.endTime * fps);
  const localFrame = frame - startFrame;
  const remainingFrames = endFrame - frame;

  const { width: videoWidth } = useVideoConfig();
  const rs = videoWidth / 1920;
  const cueScale = cue.scale ?? 1.0;
  const cardWidth = Math.round(template.cardWidth * cueScale);
  const padding = Math.round(template.padding * cueScale);
  const borderRadius = Math.round(template.borderRadius * cueScale);
  const skewX = template.skewX ?? 0;

  // Entrance
  const entrance = useEntranceAnimation(
    localFrame,
    fps,
    template.entranceType,
    template.entranceSpring,
    cue.position
  );

  // Exit
  const exit = useExitAnimation(
    remainingFrames,
    template.exitFrames,
    template.exitType,
    template.entranceType
  );

  // Idle
  const idle = useIdleAnimation(localFrame, template.idleAnimation);

  // Position
  const cueX = cue.x ?? (cue.position === "left" ? 8 : 92);
  const cueY = cue.y ?? 50;
  const anchorStyle: React.CSSProperties =
    cueX <= 50 ? { left: `${cueX}%` } : { right: `${100 - cueX}%` };

  // Resolve border with color placeholders
  const resolvedBorder = resolveColorPlaceholders(template.border, color);

  // Accent bar
  const accentBarProgress = template.accentBar
    ? interpolate(
        spring({ frame: localFrame, fps, config: template.entranceSpring }),
        [0, 1],
        [0, 100]
      )
    : 0;

  let accentBarExit = 100;
  if (template.accentBar && remainingFrames < template.exitFrames) {
    const rawP = interpolate(
      remainingFrames,
      [0, template.exitFrames],
      [0, 1],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
    );
    const aeEase = (t: number) => {
      const p = 1 - t;
      return 3 * p * t * t * 0.24 + t * t * t;
    };
    accentBarExit = aeEase(rawP) * 100;
  }
  const accentBarHeight = Math.min(accentBarProgress, accentBarExit);
  const accentPosition = template.accentPosition ?? "left";

  // Underline
  const underlineProgress = template.underline
    ? interpolate(
        spring({
          frame: Math.max(0, localFrame - 8),
          fps,
          config: template.entranceSpring,
        }),
        [0, 1],
        [0, 100]
      )
    : 0;

  let underlineExit = 100;
  if (template.underline && remainingFrames < template.exitFrames) {
    const rawP = interpolate(
      remainingFrames,
      [0, template.exitFrames],
      [0, 1],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
    );
    const aeEase = (t: number) => {
      const p = 1 - t;
      return 3 * p * t * t * 0.24 + t * t * t;
    };
    underlineExit = aeEase(rawP) * 100;
  }
  const underlineWidth = Math.min(underlineProgress, underlineExit);

  // Composite values
  const finalClipPath = exit.clipPath ?? entrance.clipPath;
  const opacity = entrance.opacity * exit.opacity;
  const combinedFilter = [entrance.filter, exit.filter].filter(Boolean).join(" ") || undefined;
  const skewTransform = skewX !== 0 ? `skewX(${skewX}deg)` : "";
  const scaleTransform = rs !== 1 ? `scale(${rs})` : "";
  const originX = cueX <= 50 ? "left" : "right";

  // Glow pulse box shadow modifier
  const glowShadow =
    idle.glowIntensity !== undefined
      ? `, 0 0 ${20 * idle.glowIntensity}px ${color}60, 0 0 ${40 * idle.glowIntensity}px ${color}30`
      : "";

  // Scan line overlay
  const scanLine = idle.scanLineY !== undefined ? (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        top: `${idle.scanLineY * 100}%`,
        height: 2,
        background: `linear-gradient(90deg, transparent, ${color}40, transparent)`,
        pointerEvents: "none",
      }}
    />
  ) : null;

  // Accent bar element
  const renderAccentBar = () => {
    if (!template.accentBar) return null;

    if (accentPosition === "top") {
      return (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: `${(100 - accentBarHeight) / 2}%`,
            width: `${accentBarHeight}%`,
            height: template.accentWidth,
            backgroundColor: color,
          }}
        />
      );
    }

    if (accentPosition === "bottom") {
      return (
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: `${(100 - accentBarHeight) / 2}%`,
            width: `${accentBarHeight}%`,
            height: template.accentWidth,
            backgroundColor: color,
          }}
        />
      );
    }

    // Default: left
    return (
      <div
        style={{
          position: "absolute",
          left: 0,
          top: template.layout === "bar" ? 0 : `${(100 - accentBarHeight) / 2}%`,
          width: template.accentWidth,
          height: `${accentBarHeight}%`,
          backgroundColor: color,
          borderRadius: template.layout === "bar" ? 0 : template.accentWidth / 2,
        }}
      />
    );
  };

  // Secondary effects element
  const secondaryEffects = template.secondaryMotion && template.secondaryMotion !== "none" ? (
    <SecondaryEffects
      motion={template.secondaryMotion}
      localFrame={localFrame}
      color={color}
      borderRadius={borderRadius}
      width={cardWidth}
    />
  ) : null;

  // --- Layout: bar ---
  if (template.layout === "bar") {
    return (
      <div
        style={{
          position: "absolute",
          top: `${cueY}%`,
          transform: `translateY(-50%) ${idle.transform} ${skewTransform} ${scaleTransform}`,
          transformOrigin: `${originX} center`,
          opacity,
          width: cardWidth,
          clipPath: finalClipPath,
          filter: combinedFilter,
          ...anchorStyle,
        }}
      >
        <div
          style={{
            width: cardWidth,
            background: resolveBackground(template.background, color),
            border: resolvedBorder,
            boxShadow: resolveBoxShadow(template.boxShadow, color) + glowShadow,
            borderRadius,
            padding,
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 16,
            boxSizing: "border-box",
            position: "relative",
            overflow: "hidden",
          }}
        >
          {renderAccentBar()}
          {children}
          {scanLine}
          {secondaryEffects}
        </div>
        {barFooter}
      </div>
    );
  }

  // --- Layout: text ---
  if (template.layout === "text") {
    return (
      <div
        style={{
          position: "absolute",
          top: `${cueY}%`,
          transform: `translateY(-50%) ${entrance.transform} ${idle.transform} ${scaleTransform}`,
          transformOrigin: `${originX} center`,
          opacity,
          width: cardWidth,
          filter: combinedFilter,
          ...anchorStyle,
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: cueX <= 50 ? "flex-start" : "flex-end",
            gap: 8,
            padding,
            position: "relative",
          }}
        >
          {children}
          {template.underline && (
            <div
              style={{
                height: 2,
                backgroundColor: color,
                width: `${underlineWidth}%`,
                marginTop: 4,
              }}
            />
          )}
          {scanLine}
        </div>
      </div>
    );
  }

  // --- Layout: card ---
  return (
    <div
      style={{
        position: "absolute",
        top: `${cueY}%`,
        transform: `translateY(-50%) ${entrance.transform} ${idle.transform} scale(${exit.scale}) ${skewTransform} ${scaleTransform}`,
        transformOrigin: `${originX} center`,
        opacity,
        width: cardWidth,
        clipPath: finalClipPath,
        filter: combinedFilter,
        ...anchorStyle,
      }}
    >
      <div
        style={{
          width: cardWidth,
          background: resolveBackground(template.background, color),
          backdropFilter:
            template.backdropBlur > 0
              ? `blur(${template.backdropBlur}px)`
              : undefined,
          WebkitBackdropFilter:
            template.backdropBlur > 0
              ? `blur(${template.backdropBlur}px)`
              : undefined,
          border: resolvedBorder,
          boxShadow: resolveBoxShadow(template.boxShadow, color) + glowShadow,
          borderRadius,
          padding,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 12,
          boxSizing: "border-box",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {renderAccentBar()}
        {children}
        {scanLine}
        {secondaryEffects}
      </div>
    </div>
  );
};
