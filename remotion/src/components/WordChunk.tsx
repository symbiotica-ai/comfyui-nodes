// ABOUTME: Renders a group of words (chunk) with animation-aware entrance
// ABOUTME: Handles chunk lifecycle: entrance transition, per-word highlighting, emoji

import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import {
  AnimationPreset,
  CaptionTemplate,
  WordChunk as WordChunkType,
} from "../types";
import { CaptionWord } from "./CaptionWord";
import { EmojiReaction } from "./EmojiReaction";
import { BackgroundPill } from "./BackgroundPill";

interface Props {
  chunk: WordChunkType;
  template: CaptionTemplate;
  fontSize: number;
  fontColor: string;
  highlightColor: string;
  showEmoji: boolean;
  animation: AnimationPreset;
}

export const WordChunk: React.FC<Props> = ({
  chunk,
  template,
  fontSize,
  fontColor,
  highlightColor,
  showEmoji,
  animation,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const chunkStartFrame = Math.round(chunk.startTime * fps);
  const framesSinceChunk = frame - chunkStartFrame;

  if (framesSinceChunk < 0) return null;

  // --- Chunk entrance varies by animation ---
  let translateY = 0;
  let chunkOpacity = 1;
  let chunkScale = 1;

  switch (animation) {
    case "Bounce": {
      const s = spring({
        frame: framesSinceChunk,
        fps,
        config: { damping: 8, stiffness: 200 },
      });
      translateY = interpolate(s, [0, 1], [-80, 0]);
      chunkOpacity = interpolate(s, [0, 1], [0, 1]);
      break;
    }

    case "Slam": {
      const s = spring({
        frame: framesSinceChunk,
        fps,
        config: { damping: 12, stiffness: 300 },
      });
      chunkScale = interpolate(s, [0, 1], [2.0, 1.0]);
      chunkOpacity = interpolate(s, [0, 1], [0, 1]);
      break;
    }

    case "Karaoke": {
      // Instant appear — no entrance animation
      break;
    }

    case "Glow": {
      const s = spring({
        frame: framesSinceChunk,
        fps,
        config: { damping: 14, stiffness: 160 },
      });
      chunkScale = interpolate(s, [0, 1], [0.9, 1.0]);
      chunkOpacity = interpolate(s, [0, 1], [0, 1]);
      break;
    }

    case "Rise": {
      // Opacity only — individual words handle their own rise
      const s = spring({
        frame: framesSinceChunk,
        fps,
        config: { damping: 14, stiffness: 120 },
      });
      chunkOpacity = interpolate(s, [0, 1], [0, 1]);
      break;
    }

    case "Pop":
    default: {
      const s = spring({
        frame: framesSinceChunk,
        fps,
        config: { damping: 14, stiffness: 180 },
      });
      translateY = interpolate(s, [0, 1], [40, 0]);
      chunkOpacity = interpolate(s, [0, 1], [0, 1]);
      break;
    }
  }

  const content = (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexWrap: "wrap",
        gap: 0,
      }}
    >
      {chunk.words.map((word, i) => {
        const currentTime = frame / fps;
        const isActive =
          currentTime >= word.start && currentTime <= word.end;
        const activeStartFrame = isActive
          ? Math.round(word.start * fps)
          : null;

        return (
          <CaptionWord
            key={i}
            word={word.word}
            isActive={isActive}
            activeStartFrame={activeStartFrame}
            wordStart={word.start}
            wordEnd={word.end}
            wordIndex={i}
            chunkStartFrame={chunkStartFrame}
            animation={animation}
            template={template}
            fontSize={fontSize}
            fontColor={fontColor}
            highlightColor={highlightColor}
          />
        );
      })}
      {showEmoji && chunk.emoji && (
        <EmojiReaction
          emoji={chunk.emoji}
          appearFrame={chunkStartFrame}
          fontSize={fontSize}
        />
      )}
    </div>
  );

  return (
    <div
      style={{
        transform: `translateY(${translateY}px) scale(${chunkScale})`,
        opacity: chunkOpacity,
        textAlign: "center",
      }}
    >
      {template.backgroundColor ? (
        <BackgroundPill
          backgroundColor={template.backgroundColor}
          borderRadius={template.borderRadius ?? 8}
          padding={fontSize * 0.4}
        >
          {content}
        </BackgroundPill>
      ) : (
        content
      )}
    </div>
  );
};
