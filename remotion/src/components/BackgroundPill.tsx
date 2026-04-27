// ABOUTME: Animated rounded-rect background pill for caption text
// ABOUTME: Smoothly adjusts size via spring when chunk changes

import React from "react";

interface Props {
  backgroundColor: string;
  borderRadius: number;
  padding: number;
}

export const BackgroundPill: React.FC<React.PropsWithChildren<Props>> = ({
  backgroundColor,
  borderRadius,
  padding,
  children,
}) => {
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor,
        borderRadius,
        padding: `${padding * 0.5}px ${padding}px`,
      }}
    >
      {children}
    </div>
  );
};
