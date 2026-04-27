// ABOUTME: TikTok feed UI overlay rendered at any resolution with transparency
// ABOUTME: Animated sidebar icons, music disc rotation, marquee text, progress bar

import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  AbsoluteFill,
  interpolate,
} from "remotion";
import { TikTokOverlayProps } from "./types";

/* ---------- SVG icons ---------- */

const iconShadow: React.CSSProperties = {
  filter: "drop-shadow(0 2px 4px rgba(0,0,0,0.5))",
};

const HeartIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="white" style={iconShadow}>
    <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
  </svg>
);

const CommentIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="white" style={iconShadow}>
    <path d="M20 2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h14l4 4V4c0-1.1-.9-2-2-2zm0 15.17L18.83 16H4V4h16v13.17z" />
    <circle cx="8" cy="10" r="1.2" />
    <circle cx="12" cy="10" r="1.2" />
    <circle cx="16" cy="10" r="1.2" />
  </svg>
);

const BookmarkIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="white" style={iconShadow}>
    <path d="M17 3H7c-1.1 0-2 .9-2 2v16l7-3 7 3V5c0-1.1-.9-2-2-2z" />
  </svg>
);

const ShareIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="white" style={iconShadow}>
    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14.5v-5H7l5-6.5v5h4l-5 6.5z" />
  </svg>
);

const MusicNoteIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="white" style={iconShadow}>
    <path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z" />
  </svg>
);

/* ---------- Sub-components ---------- */

const SidebarIcon: React.FC<{
  icon: React.ReactNode;
  count: string;
  u: number;
}> = ({ icon, count, u }) => (
  <div
    style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      marginBottom: u * 1.2,
    }}
  >
    {icon}
    <div
      style={{
        color: "white",
        fontSize: u * 1.4,
        fontWeight: 700,
        textAlign: "center",
        marginTop: u * 0.3,
        textShadow: "0 1px 4px rgba(0,0,0,0.7)",
      }}
    >
      {count}
    </div>
  </div>
);

const MusicDisc: React.FC<{ size: number; rotation: number; u: number }> = ({
  size,
  rotation,
  u,
}) => (
  <div
    style={{
      width: size,
      height: size,
      borderRadius: "50%",
      background: "radial-gradient(circle at 40% 40%, #555, #222, #111)",
      transform: `rotate(${rotation}deg)`,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      border: `${u * 0.15}px solid #555`,
      boxShadow: "0 2px 10px rgba(0,0,0,0.5)",
    }}
  >
    <div
      style={{
        width: size * 0.35,
        height: size * 0.35,
        borderRadius: "50%",
        background: "#aaa",
      }}
    />
  </div>
);

/* ---------- Main component ---------- */

export const TikTokOverlay: React.FC<TikTokOverlayProps> = ({
  username = "@creator",
  description = "",
  musicName = "Original Sound",
  likes = "1.2M",
  comments = "23.4K",
  bookmarks = "45.6K",
  shares = "12.3K",
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();

  // Base unit = 1% of height (resolution-independent sizing)
  const u = height / 100;
  const seconds = frame / fps;

  // Animations
  const fadeIn = interpolate(frame, [0, fps * 0.4], [0, 1], {
    extrapolateRight: "clamp",
  });
  const discRotation = seconds * 120;
  const progress = frame / durationInFrames;

  const marqueeWidth = u * 28;
  const marqueeOffset = (seconds * u * 3) % marqueeWidth;

  // Layout — proportions matched to real TikTok UI
  const iconSize = u * 4;
  const sideRight = u * 2.2;
  const bottomPad = u * 8;
  const discSize = u * 5;
  const avatarSize = u * 5.5;

  const textShadow = "0 1px 5px rgba(0,0,0,0.7)";

  return (
    <AbsoluteFill
      style={{
        opacity: fadeIn,
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      {/* Bottom gradient for text readability */}
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
          height: height * 0.45,
          background: "linear-gradient(transparent, rgba(0,0,0,0.5))",
        }}
      />

      {/* ---- Right sidebar ---- */}
      <div
        style={{
          position: "absolute",
          right: sideRight,
          bottom: bottomPad,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
        }}
      >
        {/* Profile avatar */}
        <div style={{ position: "relative", marginBottom: u * 2.5 }}>
          <div
            style={{
              width: avatarSize,
              height: avatarSize,
              borderRadius: "50%",
              background:
                "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
              border: `${u * 0.2}px solid white`,
              boxShadow: "0 2px 8px rgba(0,0,0,0.4)",
            }}
          />
          {/* Plus badge */}
          <div
            style={{
              position: "absolute",
              bottom: -u * 0.8,
              left: "50%",
              transform: "translateX(-50%)",
              width: u * 2,
              height: u * 2,
              borderRadius: "50%",
              background: "#FE2C55",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: u * 1.4,
              color: "white",
              fontWeight: 700,
              lineHeight: 1,
              boxShadow: "0 1px 4px rgba(0,0,0,0.4)",
            }}
          >
            +
          </div>
        </div>

        {/* Like */}
        <SidebarIcon
          icon={<HeartIcon size={iconSize} />}
          count={likes}
          u={u}
        />
        {/* Comment */}
        <SidebarIcon
          icon={<CommentIcon size={iconSize} />}
          count={comments}
          u={u}
        />
        {/* Bookmark */}
        <SidebarIcon
          icon={<BookmarkIcon size={iconSize} />}
          count={bookmarks}
          u={u}
        />
        {/* Share */}
        <SidebarIcon
          icon={<ShareIcon size={iconSize} />}
          count={shares}
          u={u}
        />

        {/* Music disc */}
        <div style={{ marginTop: u * 0.8 }}>
          <MusicDisc size={discSize} rotation={discRotation} u={u} />
        </div>
      </div>

      {/* ---- Bottom left text ---- */}
      <div
        style={{
          position: "absolute",
          left: u * 2,
          bottom: bottomPad,
          maxWidth: width * 0.6,
        }}
      >
        {/* Username */}
        <div
          style={{
            color: "white",
            fontSize: u * 1.8,
            fontWeight: 700,
            textShadow,
            marginBottom: u * 0.5,
          }}
        >
          {username}
        </div>

        {/* Description */}
        {description && (
          <div
            style={{
              color: "white",
              fontSize: u * 1.4,
              fontWeight: 400,
              textShadow,
              marginBottom: u * 0.7,
              lineHeight: 1.3,
            }}
          >
            {description}
          </div>
        )}

        {/* Music info with marquee */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: u * 0.5,
          }}
        >
          <MusicNoteIcon size={u * 1.6} />
          <div
            style={{
              overflow: "hidden",
              width: u * 24,
              whiteSpace: "nowrap",
            }}
          >
            <div
              style={{
                color: "white",
                fontSize: u * 1.3,
                fontWeight: 400,
                textShadow,
                transform: `translateX(-${marqueeOffset}px)`,
                display: "inline-block",
              }}
            >
              {musicName}
              {"   \u00A0\u00A0\u00A0   "}
              {musicName}
            </div>
          </div>
        </div>
      </div>

      {/* ---- Progress bar ---- */}
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
          height: Math.max(u * 0.2, 2),
          background: "rgba(255,255,255,0.25)",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${progress * 100}%`,
            background: "white",
          }}
        />
      </div>
    </AbsoluteFill>
  );
};
