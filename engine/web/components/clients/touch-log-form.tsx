"use client";

import { Plus, Phone, MessageCircle, Mail, Mic2, Send, Users, Edit3 } from "lucide-react";
import { ActionForm } from "@/components/ui/action-form";
import { Button } from "@/components/ui/button";
import { logTouch } from "@/app/actions";

const KINDS = [
  { value: "call", label: "Call", Icon: Phone },
  { value: "text", label: "Text", Icon: MessageCircle },
  { value: "email", label: "Email", Icon: Mail },
  { value: "in_person", label: "In person", Icon: Mic2 },
  { value: "letter", label: "Letter", Icon: Send },
  { value: "meeting", label: "Meeting", Icon: Users },
  { value: "note", label: "Note", Icon: Edit3 },
];

const INPUT_CLS =
  "h-9 rounded-md border border-(--color-input) bg-(--color-background) px-2 text-sm focus:outline-none focus:ring-2 focus:ring-(--color-ring)";

/** Inline form on the client detail page for logging a touch. Resets
 * itself on successful submit so the next entry starts clean. */
export function TouchLogForm({ clientId }: { clientId: string }) {
  return (
    <ActionForm
      action={logTouch}
      resetOnSuccess
      className="grid grid-cols-1 md:grid-cols-[140px_120px_1fr_auto] gap-2 mb-5 items-start"
    >
      <input type="hidden" name="clientId" value={clientId} />
      <select name="kind" required defaultValue="call" className={INPUT_CLS}>
        {KINDS.map((k) => (
          <option key={k.value} value={k.value}>
            {k.label}
          </option>
        ))}
      </select>
      <select name="direction" defaultValue="outbound" className={INPUT_CLS}>
        <option value="outbound">→ outbound</option>
        <option value="inbound">← inbound</option>
      </select>
      <input
        name="notes"
        placeholder="What happened? (kid's school, follow-up date, etc.)"
        className={INPUT_CLS}
      />
      <Button type="submit" size="sm">
        <Plus className="size-3.5" /> Log
      </Button>
    </ActionForm>
  );
}
