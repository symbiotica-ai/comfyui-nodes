// ABOUTME: Instagram Reels feed UI overlay rendered at any resolution with transparency
// ABOUTME: Animated sidebar icons, spinning album art, marquee music, progress bar

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

const HeartIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="white" style={iconShadow}>
    <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
  </svg>
);

const CommentIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="white" style={iconShadow}>
    <path d="M20 2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h14l4 4V4c0-1.1-.9-2-2-2z" />
  </svg>
);

const SendIcon: React.FC<{ size: number }> = ({ size }) => (
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

export const InstagramOverlay: React.FC<SocialOverlayProps> = ({
  username = "@creator",
  description = "",
  musicName = "Original Audio",
  likes = "680K",
  comments = "1,204",
  shares = "Share",
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();

  const u = height / 100;
  const seconds = frame / fps;

  const fadeIn = interpolate(frame, [0, fps * 0.4], [0, 1], {
    extrapolateRight: "clamp",
  });
  const discRotation = seconds * 90;
  const progress = frame / durationInFrames;

  const marqueeWidth = u * 28;
  const marqueeOffset = (seconds * u * 3) % marqueeWidth;

  // Layout — proportions matched to real Instagram Reels UI
  const iconSize = u * 4;
  const sideRight = u * 2.2;
  const bottomPad = u * 8;
  const discSize = u * 4.5;
  const avatarSize = u * 3.8;

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
        {/* Share / Send */}
        <SidebarIcon
          icon={<SendIcon size={iconSize} />}
          count={shares}
          u={u}
        />
        {/* More (three dots) */}
        <div style={{ marginBottom: u * 1.2 }}>
          <MoreIcon size={iconSize} />
        </div>

        {/* Spinning album art disc */}
        <div
          style={{
            width: discSize,
            height: discSize,
            borderRadius: "50%",
            background:
              "linear-gradient(135deg, #833ab4, #fd1d1d, #fcb045)",
            transform: `rotate(${discRotation}deg)`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            border: `${u * 0.15}px solid rgba(255,255,255,0.4)`,
            boxShadow: "0 2px 10px rgba(0,0,0,0.4)",
          }}
        >
          <div
            style={{
              width: discSize * 0.38,
              height: discSize * 0.38,
              borderRadius: "50%",
              background: "rgba(255,255,255,0.25)",
            }}
          />
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
        {/* Username + Follow button */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: u * 0.8,
            marginBottom: u * 0.5,
          }}
        >
          {/* Profile avatar */}
          <div
            style={{
              width: avatarSize,
              height: avatarSize,
              borderRadius: "50%",
              background:
                "linear-gradient(135deg, #833ab4, #fd1d1d, #fcb045)",
              border: `${u * 0.15}px solid white`,
              flexShrink: 0,
              boxShadow: "0 2px 6px rgba(0,0,0,0.4)",
            }}
          />
          <div
            style={{
              color: "white",
              fontSize: u * 1.7,
              fontWeight: 700,
              textShadow,
            }}
          >
            {username}
          </div>
          {/* Follow pill */}
          <div
            style={{
              background: "#0095F6",
              color: "white",
              fontSize: u * 1.15,
              fontWeight: 600,
              padding: `${u * 0.35}px ${u * 1.1}px`,
              borderRadius: u * 0.6,
              whiteSpace: "nowrap",
              boxShadow: "0 1px 4px rgba(0,0,0,0.3)",
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
