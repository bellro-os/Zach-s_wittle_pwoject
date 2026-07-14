"use client";

import { useEffect } from "react";
import { startAnimationGovernor } from "@/lib/compbird/idle-animations";

/**
 * Mounts the decorative-animation governor (idle-animations.ts) once for the
 * whole document: pauses every `[data-cb-anim]` / `.cb-marquee-track` loop
 * while the tab is hidden or the user has been idle ~30s, resumes on the next
 * interaction. Renders nothing; lives in the root layout.
 */
export function AnimationGovernor() {
  useEffect(() => startAnimationGovernor(document), []);
  return null;
}
