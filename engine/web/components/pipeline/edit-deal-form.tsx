"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Edit3 } from "lucide-react";
import { ActionForm } from "@/components/ui/action-form";
import { updateDeal } from "@/app/actions";
import { cn } from "@/lib/utils";

const INPUT_CLS =
  "w-full h-9 rounded-md border border-(--color-input) bg-(--color-background) px-2 text-sm";

export interface EditDealClient {
  id: string;
  displayId: string;
  name: string;
}

interface Props {
  deal: {
    displayId: string;
    side: string;
    property: string;
    clientId: string | null;
    listPrice: number | null;
    expectedClose: Date | null;
    estCommissionPct: number | null;
    commissionEarned: number | null;
    notes: string | null;
  };
  /** All non-deleted clients — populates the link picker. */
  clients: EditDealClient[];
  /** Custom trigger (e.g. a compact icon button on a list card). Defaults
   * to the standard "Edit deal" outline button. */
  trigger?: React.ReactNode;
}

export function EditDealForm({ deal, clients, trigger }: Props) {
  const [open, setOpen] = useState(false);
  const toISO = (d: Date | null) => (d ? d.toISOString().slice(0, 10) : "");

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button variant="outline" size="sm">
            <Edit3 className="size-3.5" />
            Edit deal
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit deal {deal.displayId}</DialogTitle>
        </DialogHeader>
        <ActionForm action={updateDeal} onSuccess={() => setOpen(false)}>
          <input type="hidden" name="displayId" value={deal.displayId} />
          <div className="space-y-2 text-sm">
            <Field label="Property *">
              <input
                name="property"
                defaultValue={deal.property}
                required
                className={INPUT_CLS}
              />
            </Field>
            <Field label="Client">
              <select
                name="clientId"
                defaultValue={deal.clientId ?? ""}
                className={INPUT_CLS}
              >
                <option value="">— No client linked —</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.displayId})
                  </option>
                ))}
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Side">
                <select name="side" defaultValue={deal.side} className={INPUT_CLS}>
                  <option value="sell">Sell side</option>
                  <option value="buy">Buy side</option>
                  <option value="rent">Rent</option>
                </select>
              </Field>
              <Field label="List / sale price">
                <input
                  type="number"
                  step="any"
                  name="listPrice"
                  defaultValue={deal.listPrice ?? ""}
                  className={INPUT_CLS}
                />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Expected close">
                <input
                  type="date"
                  name="expectedClose"
                  defaultValue={toISO(deal.expectedClose)}
                  className={INPUT_CLS}
                />
              </Field>
              <Field label="Commission %">
                <input
                  type="number"
                  step="any"
                  name="estCommissionPct"
                  defaultValue={deal.estCommissionPct ?? ""}
                  className={INPUT_CLS}
                />
              </Field>
            </div>
            <Field label="Commission earned ($) — actual; overrides the % estimate">
              <input
                type="number"
                step="any"
                name="commissionEarned"
                defaultValue={deal.commissionEarned ?? ""}
                placeholder="e.g. 4050 — your net on this deal"
                className={INPUT_CLS}
              />
            </Field>
            <Field label="Notes">
              <textarea
                name="notes"
                rows={3}
                defaultValue={deal.notes ?? ""}
                className={cn(INPUT_CLS, "h-auto py-2")}
              />
            </Field>
          </div>
          <DialogFooter className="mt-3">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit">Save</Button>
          </DialogFooter>
        </ActionForm>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[10px] uppercase tracking-wider font-semibold text-(--color-muted-foreground) block mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}
