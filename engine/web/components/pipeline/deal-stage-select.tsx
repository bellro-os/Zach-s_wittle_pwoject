"use client";

import { useTransition } from "react";
import { toast } from "sonner";
import { updateDealStage } from "@/app/actions";

interface Props {
  dealId: string;
  currentStage: string;
  stages: string[];
}

/** Tiny client component: dropdown that fires updateDealStage on change,
 * toasts the result, disables while in-flight. */
export function DealStageSelect({ dealId, currentStage, stages }: Props) {
  const [isPending, startTransition] = useTransition();

  return (
    <select
      defaultValue={currentStage}
      disabled={isPending}
      onChange={(e) => {
        const stage = e.target.value;
        const fd = new FormData();
        fd.set("dealId", dealId);
        fd.set("stage", stage);
        startTransition(async () => {
          const result = await updateDealStage(fd);
          if (result.success) toast.success(result.message ?? `Stage → ${stage}`);
          else toast.error(result.error ?? "Failed to update stage");
        });
      }}
      className="w-full text-xs rounded-md border border-(--color-input) bg-(--color-background) px-1.5 py-1"
    >
      {stages.map((opt) => (
        <option key={opt} value={opt}>
          {opt}
        </option>
      ))}
    </select>
  );
}
