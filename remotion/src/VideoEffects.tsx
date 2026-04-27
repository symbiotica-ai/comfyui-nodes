// ABOUTME: Remotion composition for video effects (zoom, wiggle, face tracking)
// ABOUTME: Renders source video with transform effects, no captions

import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Easing,
  OffthreadVideo,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { FacePosition, VideoEffectsProps } from "./types";

function getFacePosition(
  positions: FacePosition[] | null,
  currentFrame: number
): { x: number; y: number } {
  if (!positions || positions.length === 0) return { x: 0.5, y: 0.5 };
  if (currentFrame <= positions[0].frame) return positions[0];
  if (currentFrame >= positions[positions.length - 1].frame)
    return positions[positions.length - 1];

  for (let i = 0; i < positions.length - 1; i++) {
    if (
      currentFrame >= positions[i].frame &&
      currentFrame <= positions[i + 1].frame
    ) {
      const t =
        (currentFrame - positions[i].frame) /
        (positions[i + 1].frame - positions[i].frame);
      return {
        x: positions[i].x + (positions[i + 1].x - positions[i].x) * t,
        y: positions[i].y + (positions[i + 1].y - positions[i].y) * t,
      };
    }
  }
  return positions[positions.length - 1];
}

// Seeded PRNG (mulberry32) for deterministic random zoom events
function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface ZoomKeyframe {
  frame: number;
  scale: number;
}

function generateZoomKeyframes(
  durationInFrames: number,
  fps: number,
  frequency: number,
  amount: number
): ZoomKeyframe[] {
  const rng = mulberry32(durationInFrames);
  // frequency 1 → ~10s interval, frequency 10 → ~2s interval
  const avgInterval = 2 + (8 * (10 - frequency)) / 9;
  const keyframes: ZoomKeyframe[] = [{ frame: 0, scale: 1 }];
  const durationSec = durationInFrames / fps;

  let t = avgInterval * (0.5 + rng() * 0.5);
  let zoomedIn = false;
  while (t < durationSec) {
    if (zoomedIn) {
      keyframes.push({ frame: Math.round(t * fps), scale: 1 });
    } else {
      const vary = 0.8 + rng() * 0.4;
      keyframes.push({ frame: Math.round(t * fps), scale: 1 + amount * vary });
    }
    zoomedIn = !zoomedIn;
    t += avgInterval * (0.7 + rng() * 0.6);
  }

  return keyframes;
}

// Dramatic S-curve: very slow start, fast middle, very slow end
const zoomEasing = Easing.bezier(0.85, 0, 0.15, 1);

function computeZoomScale(
  keyframes: ZoomKeyframe[],
  frame: number,
  fps: number,
  speed: number
): number {
  if (keyframes.length === 0) return 1;

  let activeIdx = 0;
  for (let i = keyframes.length - 1; i >= 0; i--) {
    if (frame >= keyframes[i].frame) {
      activeIdx = i;
      break;
    }
  }

  const target = keyframes[activeIdx].scale;
  const prevScale = activeIdx > 0 ? keyframes[activeIdx - 1].scale : 1;

  const transitionFrames = Math.round((0.8 / speed) * fps);
  const elapsed = frame - keyframes[activeIdx].frame;

  const progress = interpolate(elapsed, [0, transitionFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: zoomEasing,
  });

  return prevScale + (target - prevScale) * progress;
}

// Layered sine waves at incommensurate frequencies for organic wiggle
function computeWiggle(
  frame: number,
  fps: number,
  intensity: number
): { x: number; y: number; rotation: number } {
  const t = frame / fps;
  const amp = intensity * 0.8;

  const x =
    Math.sin(t * 4.3) * amp +
    Math.sin(t * 7.1) * amp * 0.6 +
    Math.sin(t * 13.7) * amp * 0.25;

  const y =
    Math.cos(t * 5.1) * amp +
    Math.cos(t * 9.3) * amp * 0.5 +
    Math.cos(t * 15.1) * amp * 0.2;

  const rotation =
    Math.sin(t * 3.7) * intensity * 0.06 +
    Math.sin(t * 8.9) * intensity * 0.03;

  return { x, y, rotation };
}

export const VideoEffects: React.FC<VideoEffectsProps> = ({
  videoSrc,
  zoom,
  zoomAmount,
  zoomFrequency,
  zoomSpeed,
  zoomBlur,
  wiggle,
  wiggleIntensity,
  facePositions,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();

  const zoomKeyframes = useMemo(
    () =>
      zoom
        ? generateZoomKeyframes(durationInFrames, fps, zoomFrequency, zoomAmount)
        : [],
    [zoom, durationInFrames, fps, zoomFrequency, zoomAmount]
  );

  let zoomScale = 1;
  if (zoom && zoomKeyframes.length > 0) {
    zoomScale = computeZoomScale(zoomKeyframes, frame, fps, zoomSpeed);
  }

  // Blur proportional to zoom velocity
  let blurAmount = 0;
  if (zoom && zoomBlur && frame > 0 && zoomKeyframes.length > 0) {
    const prevScale = computeZoomScale(zoomKeyframes, frame - 1, fps, zoomSpeed);
    const zoomDelta = Math.abs(zoomScale - prevScale);
    blurAmount = interpolate(zoomDelta, [0, 0.01], [0, 3], {
      extrapolateRight: "clamp",
    });
  }

  // Face tracking: compute transform origin for zoom
  const facePos = getFacePosition(facePositions, frame);
  const transformOrigin = `${facePos.x * 100}% ${facePos.y * 100}%`;

  // Wiggle: organic camera shake via layered sine waves
  const wig = wiggle
    ? computeWiggle(frame, fps, wiggleIntensity)
    : { x: 0, y: 0, rotation: 0 };

  // Scale up slightly when wiggle is active to prevent black edges
  let wiggleCropScale = 1;
  if (wiggle) {
    const maxDisp = wiggleIntensity * 1.5;
    const maxRotRad = wiggleIntensity * 0.09 * (Math.PI / 180);
    const rotDisp = Math.sin(maxRotRad) * Math.max(width, height) / 2;
    wiggleCropScale = 1 + ((maxDisp + rotDisp) * 2) / Math.min(width, height);
  }

  const totalScale = zoomScale * wiggleCropScale;

  return (
    <AbsoluteFill style={{ backgroundColor: "black", overflow: "hidden" }}>
      <AbsoluteFill
        style={{
          transform: `scale(${totalScale}) translate(${wig.x}px, ${wig.y}px) rotate(${wig.rotation}deg)`,
          transformOrigin,
          filter: blurAmount > 0 ? `blur(${blurAmount}px)` : undefined,
          willChange: "transform, filter",
        }}
      >
        <OffthreadVideo src={staticFile(videoSrc)} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
