// ABOUTME: Responsive scale context and hook for resolution-independent sizing
// ABOUTME: All pixel values multiply by this factor (baseline: 1920px width)

import React, { useContext } from "react";

const BASELINE_WIDTH = 1920;

export const ResponsiveScaleContext = React.createContext(1);

/** Returns responsive scale factor. Multiply all pixel values by this. */
export function useResponsiveScale(): number {
  return useContext(ResponsiveScaleContext);
}

/** Compute scale factor from video width */
export function computeResponsiveScale(videoWidth: number): number {
  return videoWidth / BASELINE_WIDTH;
}
