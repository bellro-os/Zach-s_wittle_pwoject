"use client";

import { useEffect, useState } from "react";
import { Keyboard } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

const SHORTCUTS: { key: string; label: string }[] = [
  { key: "j / k", label: "Next / previous row" },
  { key: "i", label: "Mark Interested" },
  { key: "l", label: "Mark Talk later" },
  { key: "v", label: "Voicemail (call mode) / Left flyer (door-knock)" },
  { key: "n", label: "No answer / Nobody home" },
  { key: "x", label: "Mark Not interested" },
  { key: "b", label: "Bad number (call mode only)" },
  { key: "e", label: "Expand / collapse Why? panel" },
  { key: "o", label: "Open property page (new tab)" },
  { key: "?", label: "Open this help" },
  { key: "Esc", label: "Collapse all panels, close modal" },
];

/** Listens for `?` and opens a help dialog. The dialog itself lists every
 * shortcut. Closing returns focus to the queue. */
export function KeyboardHelp() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (e.key !== "?" && e.key !== "/") return;
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.tagName === "SELECT" ||
          t.isContentEditable)
      ) {
        return;
      }
      e.preventDefault();
      setOpen(true);
    }
    function openHandler() {
      setOpen(true);
    }
    window.addEventListener("keydown", handler);
    window.addEventListener("keyboard-help-open", openHandler);
    return () => {
      window.removeEventListener("keydown", handler);
      window.removeEventListener("keyboard-help-open", openHandler);
    };
  }, []);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="inline-flex items-center gap-2">
            <Keyboard className="size-5" /> Keyboard shortcuts
          </DialogTitle>
          <DialogDescription>
            Shortcuts pause when an input or textarea is focused.
          </DialogDescription>
        </DialogHeader>
        <table className="text-sm w-full">
          <tbody className="divide-y divide-(--color-border)">
            {SHORTCUTS.map((s) => (
              <tr key={s.key}>
                <td className="py-1.5 pr-4 w-24">
                  <kbd className="bg-(--color-muted) px-2 py-0.5 rounded font-mono text-xs">
                    {s.key}
                  </kbd>
                </td>
                <td className="py-1.5 text-(--color-muted-foreground)">
                  {s.label}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DialogContent>
    </Dialog>
  );
}
