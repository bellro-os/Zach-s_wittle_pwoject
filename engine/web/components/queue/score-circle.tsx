import { cn } from "@/lib/utils";

export function ScoreCircle({
  score,
  size = "md",
  className,
}: {
  score: number;
  size?: "sm" | "md";
  className?: string;
}) {
  const tier =
    score >= 60 ? "hi" : score >= 45 ? "mid" : "lo";
  return (
    <div
      className={cn(
        "inline-flex items-center justify-center rounded-full border-2 font-bold tabular-nums",
        size === "md" ? "size-9 text-sm" : "size-7 text-xs",
        tier === "hi" &&
          "border-(--color-success) bg-(--color-success)/10 text-(--color-success)",
        tier === "mid" &&
          "border-(--color-warning) bg-(--color-warning)/10 text-(--color-warning)",
        tier === "lo" &&
          "border-(--color-border) bg-(--color-muted) text-(--color-muted-foreground)",
        className,
      )}
    >
      {score}
    </div>
  );
}
