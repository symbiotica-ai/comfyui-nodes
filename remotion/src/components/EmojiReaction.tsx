// ABOUTME: Emoji pop-in component with bouncy spring animation
// ABOUTME: Uses Twemoji images for cross-platform rendering (no system emoji font needed)

import React from "react";
import { Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

function emojiToTwemojiUrl(emoji: string): string {
  const codepoint = [...emoji]
    .map((char) => char.codePointAt(0)!.toString(16))
    .filter((cp) => cp !== "fe0f")
    .join("-");
  return `https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/${codepoint}.png`;
}

interface Props {
  emoji: string;
  appearFrame: number;
  fontSize: number;
}

export const EmojiReaction: React.FC<Props> = ({
  emoji,
  appearFrame,
  fontSize,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const framesSince = frame - appearFrame;
  if (framesSince < 0) return null;

  const springVal = spring({
    frame: framesSince,
    fps,
    config: { damping: 8, stiffness: 180 },
  });

  const scale = interpolate(springVal, [0, 1], [0, 1]);
  const rotate = interpolate(springVal, [0, 0.5, 1], [-20, 10, 0]);
  const size = fontSize * 0.9;

  return (
    <span
      style={{
        display: "inline-block",
        transform: `scale(${scale}) rotate(${rotate}deg)`,
        marginLeft: fontSize * 0.2,
        width: size,
        height: size,
      }}
    >
      <Img
        src={emojiToTwemojiUrl(emoji)}
        style={{ width: size, height: size }}
      />
    </span>
  );
};
