"use client";

import { Toaster as SonnerToaster } from "sonner";
import { useTheme } from "@/components/theme-provider";

/** Sonner toast container — themed to match shadcn tokens. Mounted once
 * from the root layout. */
export function Toaster() {
  const { resolvedTheme } = useTheme();
  return (
    <SonnerToaster
      theme={(resolvedTheme as "light" | "dark") ?? "system"}
      position="top-right"
      richColors
      closeButton
      toastOptions={{
        classNames: {
          toast:
            "border border-(--color-border) bg-(--color-card) text-(--color-foreground) shadow-md",
          title: "text-sm font-medium",
          description: "text-xs text-(--color-muted-foreground)",
          actionButton:
            "bg-(--color-primary) text-(--color-primary-foreground) text-xs font-medium",
        },
      }}
    />
  );
}
