// ABOUTME: Facebook Reels feed UI overlay rendered at any resolution with transparency
// ABOUTME: Thumbs-up icon, Facebook Blue accents, marquee music, progress bar

import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  AbsoluteFill,
  interpolate,
} from "remotion";
import { SocialOverlayProps } from "./types";

/* ---------- SVG icons ---------- */

const iconShadow: React.CSSProperties = {
  filter: "drop-shadow(0 2px 4px rgba(0,0,0,0.5))",
};

const ThumbsUpIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="white" style={iconShadow}>
    <path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z" />
  </svg>
);

const CommentIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="white" style={iconShadow}>
    <path d="M20 2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h14l4 4V4c0-1.1-.9-2-2-2z" />
  </svg>
);

const ShareIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="white" style={iconShadow}>
    <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
  </svg>
);

const MoreIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="white" style={iconShadow}>
    <circle cx="5" cy="12" r="2.5" />
    <circle cx="12" cy="12" r="2.5" />
    <circle cx="19" cy="12" r="2.5" />
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

/* ---------- Main component ---------- */

const FB_BLUE = "#1877F2";

export const FacebookOverlay: React.FC<SocialOverlayProps> = ({
  username = "Creator Name",
  description = "",
  musicName = "Original Audio",
  likes = "12K",
  comments = "234",
  shares = "Share",
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();

  const u = height / 100;
  const seconds = frame / fps;

  const fadeIn = interpolate(frame, [0, fps * 0.4], [0, 1], {
    extrapolateRight: "clamp",
  });
  const progress = frame / durationInFrames;

  const marqueeWidth = u * 28;
  const marqueeOffset = (seconds * u * 3) % marqueeWidth;

  // Layout — proportions matched to real Facebook Reels UI
  const iconSize = u * 4;
  const sideRight = u * 2.2;
  const bottomPad = u * 8;
  const avatarSize = u * 5.5;

  const textShadow = "0 1px 5px rgba(0,0,0,0.7)";

  return (
    <AbsoluteFill
      style={{
        opacity: fadeIn,
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      {/* Bottom gradient */}
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
        {/* Profile avatar with Facebook Blue "+" badge */}
        <div style={{ position: "relative", marginBottom: u * 2.5 }}>
          <div
            style={{
              width: avatarSize,
              height: avatarSize,
              borderRadius: "50%",
              background: "linear-gradient(135deg, #4a6fa5, #6b8cce)",
              border: `${u * 0.2}px solid white`,
              boxShadow: "0 2px 8px rgba(0,0,0,0.4)",
            }}
          />
          <div
            style={{
              position: "absolute",
              bottom: -u * 0.8,
              left: "50%",
              transform: "translateX(-50%)",
              width: u * 2,
              height: u * 2,
              borderRadius: "50%",
              background: FB_BLUE,
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

        {/* Like (Thumbs Up) */}
        <SidebarIcon
          icon={<ThumbsUpIcon size={iconSize} />}
          count={likes}
          u={u}
        />
        {/* Comment */}
        <SidebarIcon
          icon={<CommentIcon size={iconSize} />}
          count={comments}
          u={u}
        />
        {/* Share */}
        <SidebarIcon
          icon={<ShareIcon size={iconSize} />}
          count={shares}
          u={u}
        />
        {/* More (three dots) */}
        <div>
          <MoreIcon size={iconSize} />
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
        {/* Creator name + Follow */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: u * 0.8,
            marginBottom: u * 0.5,
          }}
        >
          <div
            style={{
              color: "white",
              fontSize: u * 1.8,
              fontWeight: 700,
              textShadow,
            }}
          >
            {username}
          </div>
          <div
            style={{
              color: "rgba(255,255,255,0.7)",
              fontSize: u * 1.6,
              fontWeight: 500,
            }}
          >
            ·
          </div>
          <div
            style={{
              color: FB_BLUE,
              fontSize: u * 1.5,
              fontWeight: 700,
              textShadow: "0 1px 3px rgba(0,0,0,0.3)",
            }}
          >
            Follow
          </div>
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
