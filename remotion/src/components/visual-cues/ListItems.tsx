// ABOUTME: Staggered bullet list renderer with spring-based entrance
// ABOUTME: Each item enters with delay based on index

import React from "react";
import { interpolate, spring, useVideoConfig } from "remotion";

interface ListItemProps {
  text: string;
  index: number;
  localFrame: number;
  bulletColor: string;
  textShadow: string;
  fontFamily?: string;
}

const ListItem: React.FC<ListItemProps> = ({
  text,
  index,
  localFrame,
  bulletColor,
  textShadow,
  fontFamily,
}) => {
  const { fps } = useVideoConfig();
  const staggerDelay = index * 6;
  const itemFrame = Math.max(0, localFrame - staggerDelay);

  const itemSpring = spring({
    frame: itemFrame,
    fps,
    config: { damping: 12, stiffness: 400 },
  });

  const translateY = interpolate(itemSpring, [0, 1], [20, 0]);
  const opacity = interpolate(itemSpring, [0, 1], [0, 1]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 8,
        marginBottom: 8,
        transform: `translateY(${translateY}px)`,
        opacity,
      }}
    >
      <div
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          backgroundColor: bulletColor,
          marginTop: 8,
          flexShrink: 0,
        }}
      />
      <div
        style={{
          color: "rgba(255, 255, 255, 0.9)",
          fontFamily: fontFamily || "Inter, system-ui, sans-serif",
          fontWeight: 400,
          fontSize: 17,
          lineHeight: 1.4,
          textShadow,
        }}
      >
        {text}
      </div>
    </div>
  );
};

interface ListItemsProps {
  items: string[];
  localFrame: number;
  bulletColor: string;
  textShadow: string;
  fontFamily?: string;
}

export const ListItems: React.FC<ListItemsProps> = ({
  items,
  localFrame,
  bulletColor,
  textShadow,
  fontFamily,
}) => {
  return (
    <div style={{ width: "100%", marginTop: 4 }}>
      {items.map((item, i) => (
        <ListItem
          key={i}
          text={item}
          index={i}
          localFrame={localFrame}
          bulletColor={bulletColor}
          textShadow={textShadow}
          fontFamily={fontFamily}
        />
      ))}
    </div>
  );
};
