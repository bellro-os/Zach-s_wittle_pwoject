"use client";

import { useTransition, useState } from "react";
import { toast } from "sonner";
import {
  Check,
  Clock,
  Voicemail,
  PhoneOff,
  X,
  Ban,
  FileText,
  DoorClosed,
} from "lucide-react";
import {
  logCallArgs,
  logDoorknockArgs,
  deleteCall,
  deleteDoorknock,
} from "@/app/actions";
import { cn } from "@/lib/utils";

/** Minimal shape needed to log a call/knock outcome. Both Prospect (queue)
 * and ExpiredListing (/expired) satisfy this with no adapter. */
export interface ActionTarget {
  parcelId: string;
  county: string;
  owner: string;
  siteAddr: string;
}

interface OutcomeButton {
  outcome: string;
  label: string;
  shortcut: string;
  Icon: typeof Check;
  tone: "success" | "info" | "muted" | "warning" | "danger" | "neutral";
  title: string;
}

const CALL_BUTTONS: OutcomeButton[] = [
  { outcome: "interested",     label: "Interest", shortcut: "i", Icon: Check,     tone: "success", title: "Interested · follow-up in 1 day" },
  { outcome: "talk_later",     label: "Later",    shortcut: "l", Icon: Clock,     tone: "info",    title: "Talk later · follow-up in 14 days" },
  { outcome: "left_voicemail", label: "VM",       shortcut: "v", Icon: Voicemail, tone: "muted",   title: "Voicemail · follow-up in 7 days" },
  { outcome: "no_answer",      label: "NA",       shortcut: "n", Icon: PhoneOff,  tone: "muted",   title: "No answer · follow-up in 3 days" },
  { outcome: "not_interested", label: "No",       shortcut: "x", Icon: X,         tone: "danger",  title: "Not interested · suppress 1yr" },
  { outcome: "bad_number",     label: "Bad#",     shortcut: "b", Icon: Ban,       tone: "neutral", title: "Bad number · permanent suppress" },
];

const KNOCK_BUTTONS: OutcomeButton[] = [
  { outcome: "interested",     label: "Interest", shortcut: "i", Icon: Check,      tone: "success", title: "Interested · follow-up in 1 day" },
  { outcome: "talk_later",     label: "Later",    shortcut: "l", Icon: Clock,      tone: "info",    title: "Talk later · follow-up in 14 days" },
  { outcome: "left_flyer",     label: "Flyer",    shortcut: "v", Icon: FileText,   tone: "warning", title: "Left flyer · follow-up in 21 days" },
  { outcome: "nobody_home",    label: "Empty",    shortcut: "n", Icon: DoorClosed, tone: "muted",   title: "Nobody home · follow-up in 7 days" },
  { outcome: "not_interested", label: "No",       shortcut: "x", Icon: X,          tone: "danger",  title: "Not interested · suppress 1yr" },
];

const TONE_CLASSES: Record<OutcomeButton["tone"], string> = {
  success: "bg-(--color-success) text-(--color-success-foreground) hover:bg-(--color-success)/90",
  info:    "bg-(--color-info) text-(--color-info-foreground) hover:bg-(--color-info)/90",
  muted:   "bg-(--color-muted) text-(--color-foreground) hover:bg-(--color-muted)/70",
  warning: "bg-(--color-warning) text-(--color-warning-foreground) hover:bg-(--color-warning)/90",
  danger:  "border border-(--color-destructive)/30 text-(--color-destructive) hover:bg-(--color-destructive)/10",
  neutral: "border border-(--color-border) text-(--color-foreground) hover:bg-(--color-muted)/50",
};

export function ActionButtons({
  prospect,
  mode,
}: {
  prospect: ActionTarget;
  mode: "call" | "knock";
}) {
  const buttons = mode === "knock" ? KNOCK_BUTTONS : CALL_BUTTONS;
  const action = mode === "knock" ? logDoorknockArgs : logCallArgs;
  const undoAction = mode === "knock" ? deleteDoorknock : deleteCall;
  const [isPending, startTransition] = useTransition();
  const [logged, setLogged] = useState(false); // optimistic dim

  function submit(outcome: string) {
    if (isPending || logged) return;
    setLogged(true);
    startTransition(async () => {
      const result = await action({
        parcelId: prospect.parcelId,
        county: prospect.county,
        owner: prospect.owner,
        siteAddr: prospect.siteAddr,
        outcome,
        notes: "",
      });
      if (result.success) {
        const insertedId =
          result.data && typeof result.data === "object"
            ? (result.data as { callId?: number; knockId?: number }).callId ??
              (result.data as { callId?: number; knockId?: number }).knockId
            : null;
        toast.success(result.message ?? "Logged", {
          action: insertedId
            ? {
                label: "Undo",
                onClick: async () => {
                  const undo = await undoAction(insertedId);
                  if (undo.success) {
                    setLogged(false);
                    toast.success("Reverted");
                  } else {
                    toast.error(undo.error ?? "Could not undo");
                  }
                },
              }
            : undefined,
        });
      } else {
        setLogged(false);
        toast.error(result.error ?? "Failed to log");
      }
    });
  }

  return (
    <div
      data-action-row
      className={cn(
        "flex items-center gap-1.5 transition-opacity",
        (isPending || logged) && "opacity-50 pointer-events-none",
      )}
      data-parcel-id={prospect.parcelId}
    >
      {buttons.map((b) => (
        <button
          key={b.outcome}
          type="button"
          data-outcome={b.outcome}
          data-shortcut={b.shortcut}
          title={b.title}
          onClick={(e) => {
            // Stop the click from also toggling the parent <details>
            // (the queue row uses a <summary> wrapper that would otherwise
            // collapse/expand on every outcome log).
            e.stopPropagation();
            e.preventDefault();
            submit(b.outcome);
          }}
          className={cn(
            "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-all hover:shadow-sm active:scale-[0.97]",
            TONE_CLASSES[b.tone],
          )}
        >
          <b.Icon className="size-3.5" />
          {b.label}
        </button>
      ))}
    </div>
  );
}
