"use client";

import { useState } from "react";
import { Plus, Edit3 } from "lucide-react";
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
import { ClientFormFields } from "@/components/clients/client-form-fields";
import { ActionForm } from "@/components/ui/action-form";
import { addClient, updateClient } from "@/app/actions";

interface ClientDefaults {
  id?: string;
  name?: string;
  phone?: string;
  altPhone?: string;
  email?: string;
  source?: string;
  category?: string;
  tags?: string;
  anniversary?: Date | string | null;
  birthday?: Date | string | null;
  parcelId?: string;
  county?: string;
  referredById?: string;
  notes?: string;
}

interface Props {
  mode: "add" | "edit";
  defaults?: ClientDefaults;
  allClients?: { id: string; displayId: string; name: string }[];
  /** Optional trigger element. When omitted, a default button renders. */
  trigger?: React.ReactNode;
}

/** Reusable add / edit modal. Auto-closes on success, resets fields on add. */
export function ClientModal({ mode, defaults, allClients, trigger }: Props) {
  const [open, setOpen] = useState(false);

  const isEdit = mode === "edit";
  const action = isEdit ? updateClient : addClient;
  const title = isEdit ? "Edit client" : "New client";

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button variant={isEdit ? "outline" : "default"} size={isEdit ? "sm" : "default"}>
            {isEdit ? (
              <>
                <Edit3 className="size-3.5" /> Edit
              </>
            ) : (
              <>
                <Plus className="size-4" /> Add client
              </>
            )}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update the client's contact info, segmentation, and home parcel."
              : "Add a new client to your CRM."}
          </DialogDescription>
        </DialogHeader>
        <ActionForm
          action={action}
          resetOnSuccess={!isEdit}
          onSuccess={() => setOpen(false)}
        >
          <ClientFormFields defaults={defaults} allClients={allClients} />
          <DialogFooter className="mt-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit">{isEdit ? "Save changes" : "Add client"}</Button>
          </DialogFooter>
        </ActionForm>
      </DialogContent>
    </Dialog>
  );
}
