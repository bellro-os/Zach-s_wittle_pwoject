import { cn } from "@/lib/utils";

/** Shadcn-style Skeleton — pulses while async content loads. */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-(--color-muted)",
        className,
      )}
      {...props}
    />
  );
}
