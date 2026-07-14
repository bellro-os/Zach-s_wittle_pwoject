"use client";

import {
  ReactNode,
  useTransition,
  FormHTMLAttributes,
  useRef,
} from "react";
import { toast } from "sonner";
import type { ActionResult } from "@/app/actions";

interface Props
  extends Omit<FormHTMLAttributes<HTMLFormElement>, "action" | "onSubmit"> {
  /** Server action — receives FormData, returns an ActionResult. */
  action: (formData: FormData) => Promise<ActionResult>;
  /** Called with action.data on success. Useful for closing modals or
   * navigating after submit. */
  onSuccess?: (data: unknown) => void;
  onError?: (error: string) => void;
  /** Reset all form fields when the action succeeds. */
  resetOnSuccess?: boolean;
  /** Suppress success toasts. Errors still toast. */
  silentSuccess?: boolean;
  children: ReactNode;
}

/** Form wrapper that handles toast feedback + reset + pending state for
 * any server action returning ActionResult. */
export function ActionForm({
  action,
  onSuccess,
  onError,
  resetOnSuccess,
  silentSuccess,
  children,
  ...formProps
}: Props) {
  const [isPending, startTransition] = useTransition();
  const formRef = useRef<HTMLFormElement>(null);

  return (
    <form
      ref={formRef}
      {...formProps}
      onSubmit={(e) => {
        e.preventDefault();
        const fd = new FormData(e.currentTarget);
        startTransition(async () => {
          const result = await action(fd);
          if (result.success) {
            if (!silentSuccess && result.message) toast.success(result.message);
            if (resetOnSuccess) formRef.current?.reset();
            onSuccess?.(result.data);
          } else {
            const err = result.error || "Something went wrong";
            toast.error(err);
            onError?.(err);
          }
        });
      }}
    >
      {/* `contents` disables visible nesting; fieldset disables children
          while in-flight to prevent double-submits. */}
      <fieldset disabled={isPending} className="contents">
        {children}
      </fieldset>
    </form>
  );
}
