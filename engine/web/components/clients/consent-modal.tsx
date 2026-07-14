"use client";

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ShieldCheck } from "lucide-react";

const STORAGE_KEY = "recording-consent-acknowledged";

/** Shows a one-time reminder about telling the other party. Once dismissed,
 * stays dismissed (localStorage). */
export function ConsentModal({
  open,
  onAcknowledged,
  onCancel,
}: {
  open: boolean;
  onAcknowledged: () => void;
  onCancel: () => void;
}) {
  const [needsConsent, setNeedsConsent] = useState(false);

  useEffect(() => {
    if (open) {
      const acknowledged = localStorage.getItem(STORAGE_KEY) === "yes";
      setNeedsConsent(!acknowledged);
      if (acknowledged) {
        onAcknowledged();
      }
    }
  }, [open, onAcknowledged]);

  if (!needsConsent) return null;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="inline-flex items-center gap-2">
            <ShieldCheck className="size-5 text-(--color-success)" />
            Before you record
          </DialogTitle>
          <DialogDescription>
            Virginia is a one-party-consent state — you can legally record any
            call you&apos;re part of. Best practice (and good vibes): tell the
            other party first. Something like &ldquo;mind if I record this so I
            can take better notes?&rdquo; works.
          </DialogDescription>
        </DialogHeader>
        <p className="text-xs text-(--color-muted-foreground)">
          Audio is stored locally on this laptop only. Nothing leaves your
          machine except for transcription via Deepgram (encrypted in transit).
        </p>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              localStorage.setItem(STORAGE_KEY, "yes");
              onAcknowledged();
            }}
          >
            I&apos;ll mention it — record
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
