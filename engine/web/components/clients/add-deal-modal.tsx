"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ActionForm } from "@/components/ui/action-form";
import { addDeal } from "@/app/actions";
import { cn } from "@/lib/utils";

const STAGES = ["lead", "listing", "showing", "offer", "contract", "closing", "closed"];
const INPUT_CLS =
  "w-full h-9 rounded-md border border-(--color-input) bg-(--color-background) px-2 text-sm focus:outline-none focus:ring-2 focus:ring-(--color-ring)";

interface Props {
  /** Pre-fill the client (uses internal cuid). When set, the picker is hidden. */
  clientCuid?: string;
  /** Optional pre-fill of client display id (legacy text input). */
  clientDisplayId?: string;
  /** Optional pre-fill of property address. */
  propertyDefault?: string;
  trigger?: React.ReactNode;
  buttonLabel?: string;
}

export function AddDealModal({
  clientCuid,
  clientDisplayId,
  propertyDefault,
  trigger,
  buttonLabel = "Add deal",
}: Props) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button>
            <Plus className="size-4" /> {buttonLabel}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New deal</DialogTitle>
          <DialogDescription>
            Add a deal to the pipeline. Link it to an existing client via their ID for cross-page visibility.
          </DialogDescription>
        </DialogHeader>
        <ActionForm
          action={addDeal}
          resetOnSuccess
          onSuccess={() => setOpen(false)}
        >
          {clientCuid && <input type="hidden" name="clientCuid" value={clientCuid} />}
          <div className="space-y-2 text-sm">
            {!clientCuid && (
              <input
                name="clientId"
                placeholder="Client ID (e.g. C0001) — optional"
                defaultValue={clientDisplayId ?? ""}
                className={INPUT_CLS}
              />
            )}
            <div className="grid grid-cols-2 gap-2">
              <select name="stage" defaultValue="lead" className={INPUT_CLS}>
                {STAGES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <select name="side" defaultValue="sell" className={INPUT_CLS}>
                <option value="sell">Sell side</option>
                <option value="buy">Buy side</option>
                <option value="rent">Rent</option>
              </select>
            </div>
            <input
              name="property"
              required
              placeholder="Property address"
              defaultValue={propertyDefault ?? ""}
              className={INPUT_CLS}
            />
            <div className="grid grid-cols-2 gap-2">
              <input
                name="listPrice"
                type="number"
                step="any"
                placeholder="List / sale price ($)"
                className={INPUT_CLS}
              />
              <input
                name="expectedClose"
                type="date"
                className={INPUT_CLS}
              />
            </div>
            <input
              name="estCommissionPct"
              type="number"
              step="any"
              defaultValue="3.0"
              placeholder="Est. commission %"
              className={INPUT_CLS}
            />
            <textarea
              name="notes"
              rows={2}
              placeholder="Notes"
              className={cn(INPUT_CLS, "h-auto py-2")}
            />
          </div>
          <DialogFooter className="mt-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit">Save deal</Button>
          </DialogFooter>
        </ActionForm>
      </DialogContent>
    </Dialog>
  );
}
