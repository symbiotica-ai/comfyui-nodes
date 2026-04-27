// ABOUTME: Remotion root component that registers CaptionOverlay and VideoEffects compositions
// ABOUTME: Uses calculateMetadata to dynamically set dimensions/duration from props

import React from "react";
import { Composition } from "remotion";
import { CaptionOverlay } from "./CaptionOverlay";
import { VideoEffects } from "./VideoEffects";
import { VisualOverlay } from "./VisualOverlay";
import { TikTokOverlay } from "./TikTokOverlay";
import { InstagramOverlay } from "./InstagramOverlay";
import { FacebookOverlay } from "./FacebookOverlay";
import { CaptionProps, VideoEffectsProps, VisualOverlayProps, SocialOverlayProps } from "./types";

const captionDefaultProps: CaptionProps = {
  words: [],
  template: "Hormozi",
  animation: "Pop",
  position: 75,
  fontSize: 58,
  wordsPerLine: 3,
  fontColor: null,
  highlightColor: null,
  emojis: true,
  width: 1920,
  height: 1080,
  fps: 30,
  durationInFrames: 300,
};

const videoEffectsDefaultProps: VideoEffectsProps = {
  videoSrc: "source.mp4",
  zoom: false,
  zoomAmount: 0.05,
  zoomFrequency: 5,
  zoomSpeed: 1.0,
  zoomBlur: true,
  wiggle: false,
  wiggleIntensity: 3,
  faceTracking: false,
  facePositions: null,
  width: 1920,
  height: 1080,
  fps: 30,
  durationInFrames: 300,
};

const visualOverlayDefaultProps: VisualOverlayProps = {
  cues: [],
  width: 1920,
  height: 1080,
  fps: 30,
  durationInFrames: 300,
};

const tikTokDefaultProps: SocialOverlayProps = {
  username: "@creator",
  description: "",
  musicName: "Original Sound",
  likes: "1.2M",
  comments: "23.4K",
  bookmarks: "45.6K",
  shares: "12.3K",
  width: 1080,
  height: 1920,
  fps: 30,
  durationInFrames: 300,
};

const calculateMetadata = ({ props }: { props: Record<string, unknown> }) => {
  const p = props as unknown as { durationInFrames: number; fps: number; width: number; height: number };
  return {
    durationInFrames: p.durationInFrames,
    fps: p.fps,
    width: p.width,
    height: p.height,
  };
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="CaptionOverlay"
        component={CaptionOverlay as unknown as React.ComponentType<Record<string, unknown>>}
        durationInFrames={300}
        fps={30}
        width={1920}
        height={1080}
        calculateMetadata={calculateMetadata}
        defaultProps={captionDefaultProps as unknown as Record<string, unknown>}
      />
      <Composition
        id="VideoEffects"
        component={VideoEffects as unknown as React.ComponentType<Record<string, unknown>>}
        durationInFrames={300}
        fps={30}
        width={1920}
        height={1080}
        calculateMetadata={calculateMetadata}
        defaultProps={videoEffectsDefaultProps as unknown as Record<string, unknown>}
      />
      <Composition
        id="VisualOverlay"
        component={VisualOverlay as unknown as React.ComponentType<Record<string, unknown>>}
        durationInFrames={300}
        fps={30}
        width={1920}
        height={1080}
        calculateMetadata={calculateMetadata}
        defaultProps={visualOverlayDefaultProps as unknown as Record<string, unknown>}
      />
      <Composition
        id="TikTokOverlay"
        component={TikTokOverlay as unknown as React.ComponentType<Record<string, unknown>>}
        durationInFrames={300}
        fps={30}
        width={1080}
        height={1920}
        calculateMetadata={calculateMetadata}
        defaultProps={tikTokDefaultProps as unknown as Record<string, unknown>}
      />
      <Composition
        id="InstagramOverlay"
        component={InstagramOverlay as unknown as React.ComponentType<Record<string, unknown>>}
        durationInFrames={300}
        fps={30}
        width={1080}
        height={1920}
        calculateMetadata={calculateMetadata}
        defaultProps={{
          ...tikTokDefaultProps,
          likes: "680K",
          comments: "1,204",
          shares: "Share",
          musicName: "Original Audio",
        } as unknown as Record<string, unknown>}
      />
      <Composition
        id="FacebookOverlay"
        component={FacebookOverlay as unknown as React.ComponentType<Record<string, unknown>>}
        durationInFrames={300}
        fps={30}
        width={1080}
        height={1920}
        calculateMetadata={calculateMetadata}
        defaultProps={{
          ...tikTokDefaultProps,
          username: "Creator Name",
          likes: "12K",
          comments: "234",
          shares: "Share",
          musicName: "Original Audio",
        } as unknown as Record<string, unknown>}
      />
    </>
  );
};
