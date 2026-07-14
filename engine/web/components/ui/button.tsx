import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

// Ratified "Ink & Emerald": the default button is an emerald pill with a glow;
// outline/ghost/secondary stay on the ink surfaces with white/10 borders and an
// emerald-tinted hover. Public API (variant/size names) is unchanged.
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-semibold transition-all duration-300 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 [&_svg]:shrink-0 outline-none focus-visible:ring-2 focus-visible:ring-(--color-ring) focus-visible:ring-offset-2 focus-visible:ring-offset-(--color-background)",
  {
    variants: {
      variant: {
        default:
          "bg-emerald-400 text-ink-950 shadow-[0_0_28px_rgba(16,185,129,0.35)] hover:bg-emerald-300 hover:shadow-[0_0_44px_rgba(16,185,129,0.5)]",
        destructive:
          "bg-(--color-destructive) text-ink-950 shadow-xs hover:bg-(--color-destructive)/90",
        outline:
          "border border-white/15 bg-white/5 text-(--color-foreground) backdrop-blur hover:border-emerald-500/25 hover:bg-emerald-500/10 hover:text-emerald-200",
        secondary:
          "bg-(--color-secondary) text-(--color-secondary-foreground) border border-white/10 hover:border-emerald-500/25 hover:bg-(--color-secondary)/80",
        ghost:
          "hover:bg-emerald-500/10 hover:text-emerald-200",
        link: "rounded-none text-emerald-300 underline-offset-4 hover:text-emerald-200 hover:underline",
      },
      size: {
        default: "h-9 px-5 py-2 has-[>svg]:px-4",
        sm: "h-8 gap-1.5 px-4 has-[>svg]:px-3",
        lg: "h-11 px-6 has-[>svg]:px-5",
        icon: "size-9 rounded-full",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ComponentProps<"button">,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { buttonVariants };
