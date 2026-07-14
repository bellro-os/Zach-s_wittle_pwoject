import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

// Ratified "Ink & Emerald": badges are pills. Tinted variants use a low-alpha
// fill + matching /25 border (the signature emerald-500/10 + /25 pattern).
const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-full border px-2.5 py-0.5 text-xs font-medium w-fit whitespace-nowrap shrink-0 [&>svg]:size-3 gap-1 [&>svg]:pointer-events-none transition-[color,box-shadow] overflow-hidden",
  {
    variants: {
      variant: {
        default:
          "border-emerald-500/25 bg-emerald-500/10 text-emerald-300",
        secondary:
          "border-white/10 bg-(--color-secondary) text-(--color-secondary-foreground)",
        destructive:
          "border-rose-400/25 bg-rose-400/10 text-rose-300",
        outline: "border-white/15 text-(--color-foreground)",
        success:
          "border-emerald-500/25 bg-emerald-500/10 text-emerald-300",
        warning:
          "border-amber-400/25 bg-amber-400/10 text-amber-300",
        info: "border-sky-400/25 bg-sky-400/10 text-sky-300",
        danger:
          "border-rose-400/25 bg-rose-400/10 text-rose-300",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  asChild?: boolean;
}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span
      data-slot="badge"
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  );
}

export { badgeVariants };
