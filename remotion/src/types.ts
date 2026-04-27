// ABOUTME: TypeScript type definitions for the caption and video effects rendering system
// ABOUTME: Shared interfaces for words, templates, captions, and video effects props

export interface Word {
  word: string;
  start: number;
  end: number;
}

export interface CaptionTemplate {
  fontFamily: string;
  fontWeight: number;
  fontColor: string;
  highlightColor: string;
  textShadow: string;
  backgroundColor?: string;
  borderRadius?: number;
  uppercase: boolean;
  wordSpring: { damping: number; stiffness: number };
}

export type AnimationPreset = 'Pop' | 'Bounce' | 'Slam' | 'Karaoke' | 'Glow' | 'Rise';

export interface FacePosition {
  frame: number;
  x: number;
  y: number;
}

export interface WordChunk {
  words: Word[];
  startTime: number;
  endTime: number;
  emoji?: string;
}

// Shared video metadata
interface VideoMeta {
  width: number;
  height: number;
  fps: number;
  durationInFrames: number;
}

// Caption props — renders on transparent or on embedded video background
export interface CaptionProps extends VideoMeta {
  words: Word[];
  template: string;
  animation: AnimationPreset;
  position: number;
  fontSize: number;
  wordsPerLine: number;
  fontColor: string | null;
  highlightColor: string | null;
  emojis: boolean;
  videoSrc?: string | null;
}

// Visual cue types for infographic overlays
export type CueType =
  | 'icon' | 'stat' | 'label' | 'list'
  | 'progress' | 'comparison' | 'callout' | 'counter'
  | 'badge' | 'quote' | 'steps' | 'chart';
export type CuePosition = 'left' | 'right';
export type CueStyle =
  | 'cinematic' | 'bold' | 'broadcast' | 'minimal'
  | 'glass' | 'neon' | 'editorial' | 'sports' | 'social' | 'tech';

export type EntranceType =
  | 'slide-reveal' | 'scale-bounce' | 'wipe' | 'fade-slide'
  | 'blur-reveal' | 'flicker' | 'clip-reveal' | 'slam-in' | 'pop-in' | 'typewriter';
export type ExitType = 'fade' | 'scale-down' | 'wipe-out' | 'blur-out' | 'flicker-out';
export type IdleAnimation = 'float' | 'pulse' | 'none' | 'breathe' | 'glow-pulse' | 'wiggle' | 'scan-line';
export type SecondaryMotion = 'none' | 'shimmer' | 'border-trace' | 'particle-trail';

export interface ChartDataPoint {
  label: string;
  value: number;
  color?: string;
}

export interface VisualCue {
  type: CueType;
  position: CuePosition;
  startTime: number;
  endTime: number;
  icon: string;
  title: string;
  value?: string;
  items?: string[];
  x?: number;
  y?: number;
  scale?: number;
  style?: CueStyle;
  color?: string;
  // New fields for expanded cue types
  description?: string;
  prefix?: string;
  suffix?: string;
  leftLabel?: string;
  leftValue?: number;
  rightLabel?: string;
  rightValue?: number;
  text?: string;
  attribution?: string;
  activeStep?: number;
  data?: ChartDataPoint[];
  chartType?: 'bar' | 'donut';
}

export interface VisualCueTemplate {
  layout: 'card' | 'bar' | 'text';
  cardWidth: number;
  borderRadius: number;
  padding: number;
  background: string;
  backdropBlur: number;
  border: string;
  boxShadow: string;
  accentBar: boolean;
  accentWidth: number;
  underline: boolean;
  iconBackground: boolean;
  iconGlow: boolean;
  titleWeight: number;
  titleSize: number;
  valueSize: number;
  textShadow: string;
  entranceType: EntranceType;
  entranceSpring: { damping: number; stiffness: number };
  idleAnimation: IdleAnimation;
  exitFrames: number;
  exitType?: ExitType;
  secondaryMotion?: SecondaryMotion;
  skewX?: number;
  accentPosition?: 'left' | 'top' | 'bottom';
  fontFamily?: string;
  uppercase?: boolean;
}

// Visual overlay props (transparent overlay with infographic cues)
export interface VisualOverlayProps extends VideoMeta {
  cues: VisualCue[];
  defaultStyle?: CueStyle;
}

// Shared props for social media feed overlays (TikTok, Instagram, Facebook)
export interface SocialOverlayProps extends VideoMeta {
  username: string;
  description: string;
  musicName: string;
  likes: string;
  comments: string;
  bookmarks: string;
  shares: string;
}

// TikTok uses the full set; Instagram/Facebook use a subset
export type TikTokOverlayProps = SocialOverlayProps;

// Video effects props (embedded video + transforms)
export interface VideoEffectsProps extends VideoMeta {
  videoSrc: string;
  zoom: boolean;
  zoomAmount: number;
  zoomFrequency: number;
  zoomSpeed: number;
  zoomBlur: boolean;
  wiggle: boolean;
  wiggleIntensity: number;
  faceTracking: boolean;
  facePositions: FacePosition[] | null;
}
