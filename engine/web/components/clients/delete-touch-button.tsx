"use client";

import { useTransition } from "react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogTrigger,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogAction,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog";
import { deleteTouch } from "@/app/actions";

interface Props {
  touchId: string;
  clientId: string;
  preview?: string;
}

/** Inline delete trigger that requires AlertDialog confirmation. */
export function DeleteTouchButton({ touchId, clientId, preview }: Props) {
  const [isPending, startTransition] = useTransition();

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <button
          type="button"
          className="text-[10px] text-(--color-muted-foreground) hover:text-(--color-destructive)"
        >
          delete
        </button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this touch?</AlertDialogTitle>
          <AlertDialogDescription>
            This permanently removes the record from the client&apos;s timeline.
            {preview ? (
              <span className="block mt-2 italic text-(--color-foreground)">
                &ldquo;{preview}&rdquo;
              </span>
            ) : null}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={isPending}
            onClick={(e) => {
              e.preventDefault();
              startTransition(async () => {
                const fd = new FormData();
                fd.set("id", touchId);
                fd.set("clientId", clientId);
                const result = await deleteTouch(fd);
                if (result.success) toast.success("Touch deleted");
                else toast.error(result.error ?? "Could not delete");
              });
            }}
          >
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
