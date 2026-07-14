"use client";

import { useEffect } from "react";

/** Keyboard shortcut handler for the queue. Mounts once on the queue page.
 *
 * The queue-table renders each row as `<details data-row-key="…">` with an
 * action-buttons row inside containing `<button data-outcome="…"
 * data-shortcut="…">`. This handler walks those data attributes — no React
 * state needed (highlight is a DOM class). */
const OUTCOME_KEYS = new Set(["i", "l", "v", "n", "x", "b"]);
const NAV_KEYS = new Set(["j", "k"]);
const TOGGLE_KEY = "e";
const OPEN_KEY = "o";

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return (
    el.tagName === "INPUT" ||
    el.tagName === "TEXTAREA" ||
    el.tagName === "SELECT" ||
    el.isContentEditable
  );
}

function rows(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>("details[data-row-key]"),
  );
}

function currentIndex(): number {
  const all = rows();
  const i = all.findIndex((r) => r.dataset.active === "true");
  return i;
}

function setActive(index: number) {
  const all = rows();
  if (!all.length) return;
  const clamped = Math.max(0, Math.min(all.length - 1, index));
  all.forEach((r, i) => {
    if (i === clamped) r.dataset.active = "true";
    else delete r.dataset.active;
  });
  all[clamped].scrollIntoView({ block: "nearest", behavior: "smooth" });
}

export function QueueKeyboard() {
  useEffect(() => {
    // On first load, highlight the first row
    const first = rows()[0];
    if (first && currentIndex() === -1) first.dataset.active = "true";

    function handler(e: KeyboardEvent) {
      if (isTyping(e.target)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      const key = e.key.toLowerCase();
      const all = rows();
      if (!all.length) return;

      // Navigation
      if (NAV_KEYS.has(key)) {
        e.preventDefault();
        const cur = currentIndex();
        const next = cur === -1 ? 0 : cur + (key === "j" ? 1 : -1);
        setActive(next);
        return;
      }

      // Escape: collapse all open <details>
      if (e.key === "Escape") {
        document
          .querySelectorAll<HTMLDetailsElement>("details[data-row-key][open]")
          .forEach((d) => (d.open = false));
        return;
      }

      // The rest target the active row
      const cur = currentIndex();
      const activeRow = cur >= 0 ? all[cur] : all[0];
      if (!activeRow) return;

      // Toggle expansion
      if (key === TOGGLE_KEY) {
        e.preventDefault();
        const det = activeRow as HTMLDetailsElement;
        det.open = !det.open;
        return;
      }

      // Open property page in new tab
      if (key === OPEN_KEY) {
        e.preventDefault();
        const a = activeRow.querySelector<HTMLAnchorElement>(
          "a[href*='/property/']",
        );
        if (a) window.open(a.href, "_blank", "noopener,noreferrer");
        return;
      }

      // Outcome buttons
      if (OUTCOME_KEYS.has(key)) {
        const btn = activeRow.querySelector<HTMLButtonElement>(
          `button[data-shortcut="${key}"]`,
        );
        if (btn) {
          e.preventDefault();
          btn.click();
        }
      }
    }

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return null;
}
