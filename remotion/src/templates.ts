// ABOUTME: Caption template preset configurations (font, colors, animations)
// ABOUTME: Defines visual styles like Hormozi, Beast, Clean, Neon, Minimal

import { CaptionTemplate } from "./types";

export const TEMPLATES: Record<string, CaptionTemplate> = {
  Hormozi: {
    fontFamily: "Montserrat, Arial Black, sans-serif",
    fontWeight: 800,
    fontColor: "#FFFFFF",
    highlightColor: "#FFD700",
    textShadow:
      "3px 3px 0 #000, -3px -3px 0 #000, 3px -3px 0 #000, -3px 3px 0 #000, " +
      "0 3px 0 #000, 0 -3px 0 #000, 3px 0 0 #000, -3px 0 0 #000",
    uppercase: true,
    wordSpring: { damping: 12, stiffness: 200 },
  },
  Beast: {
    fontFamily: "Impact, Arial Black, sans-serif",
    fontWeight: 900,
    fontColor: "#FFFFFF",
    highlightColor: "#FF0000",
    textShadow:
      "4px 4px 0 #000, -4px -4px 0 #000, 4px -4px 0 #000, -4px 4px 0 #000, " +
      "0 4px 0 #000, 0 -4px 0 #000, 4px 0 0 #000, -4px 0 0 #000",
    uppercase: true,
    wordSpring: { damping: 10, stiffness: 250 },
  },
  Clean: {
    fontFamily: "Montserrat, Helvetica, Arial, sans-serif",
    fontWeight: 700,
    fontColor: "#1A1A2E",
    highlightColor: "#4361EE",
    textShadow: "none",
    backgroundColor: "rgba(255, 255, 255, 0.92)",
    borderRadius: 12,
    uppercase: false,
    wordSpring: { damping: 14, stiffness: 180 },
  },
  Neon: {
    fontFamily: "Montserrat, Arial Black, sans-serif",
    fontWeight: 800,
    fontColor: "#FFFFFF",
    highlightColor: "#00FFFF",
    textShadow:
      "0 0 10px rgba(0,255,255,0.8), 0 0 20px rgba(0,255,255,0.4), " +
      "2px 2px 0 #000, -2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000",
    uppercase: true,
    wordSpring: { damping: 11, stiffness: 220 },
  },
  Minimal: {
    fontFamily: "Montserrat, Helvetica, Arial, sans-serif",
    fontWeight: 600,
    fontColor: "#E0E0E0",
    highlightColor: "#FF6B35",
    textShadow: "1px 1px 3px rgba(0,0,0,0.8)",
    backgroundColor: "rgba(0, 0, 0, 0.55)",
    borderRadius: 8,
    uppercase: false,
    wordSpring: { damping: 15, stiffness: 160 },
  },
};
