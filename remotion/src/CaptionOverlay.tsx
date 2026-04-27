// ABOUTME: Remotion composition for animated caption overlay on transparent background
// ABOUTME: Renders spring-animated word-by-word captions with emoji support

import React, { useMemo } from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { CaptionProps, Word, WordChunk as WordChunkType } from "./types";
import { TEMPLATES } from "./templates";
import { findEmoji } from "./emoji-map";
import { WordChunk } from "./components/WordChunk";

const SENTENCE_END = /[.!?;·]$/;
const PAUSE_THRESHOLD = 0.3; // seconds

function buildChunks(
  words: Word[],
  wordsPerLine: number,
  withEmoji: boolean
): WordChunkType[] {
  const chunks: WordChunkType[] = [];
  let current: Word[] = [];

  const flush = () => {
    if (current.length === 0) return;
    const startTime = current[0].start;
    const endTime = current[current.length - 1].end;
    const emoji = withEmoji
      ? findEmoji(current.map((w) => w.word))
      : undefined;
    chunks.push({ words: [...current], startTime, endTime, emoji });
    current = [];
  };

  for (let i = 0; i < words.length; i++) {
    const word = words[i];
    current.push(word);

    const atMaxWords = current.length >= wordsPerLine;
    const atSentenceEnd = SENTENCE_END.test(word.word);
    const hasGap =
      i < words.length - 1 && words[i + 1].start - word.end >= PAUSE_THRESHOLD;

    if (atMaxWords || atSentenceEnd || hasGap) {
      flush();
    }
  }

  flush();
  return chunks;
}

export const CaptionOverlay: React.FC<CaptionProps> = ({
  words,
  template: templateName,
  position,
  fontSize,
  wordsPerLine,
  fontColor: fontColorOverride,
  highlightColor: highlightColorOverride,
  emojis,
  animation,
  videoSrc,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const template = TEMPLATES[templateName] ?? TEMPLATES.Hormozi;

  const fontColor = fontColorOverride || template.fontColor;
  const highlightColor = highlightColorOverride || template.highlightColor;

  const chunks = useMemo(
    () => buildChunks(words, wordsPerLine, emojis),
    [words, wordsPerLine, emojis]
  );

  // Find which chunk is active at the current time
  const currentTime = frame / fps;
  const activeChunk = chunks.find(
    (c) => currentTime >= c.startTime && currentTime <= c.endTime
  );

  // Position: 0 = top (5%), 100 = bottom (90%)
  const topPercent = 5 + (position / 100) * 85;

  return (
    <AbsoluteFill style={{ backgroundColor: videoSrc ? "black" : "transparent" }}>
      {videoSrc && (
        <OffthreadVideo
          src={staticFile(videoSrc)}
          style={{ width: "100%", height: "100%" }}
        />
      )}
      <div
        style={{
          position: "absolute",
          top: `${topPercent}%`,
          left: "5%",
          right: "5%",
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        {activeChunk && (
          <WordChunk
            chunk={activeChunk}
            template={template}
            fontSize={fontSize}
            fontColor={fontColor}
            highlightColor={highlightColor}
            showEmoji={emojis}
            animation={animation}
          />
        )}
      </div>
    </AbsoluteFill>
  );
};
