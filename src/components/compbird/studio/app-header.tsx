import Link from "next/link";
import { Wordmark } from "@/components/compbird/brand";
import { StudioAccountMenu } from "@/components/compbird/studio/account-menu";
import { cn } from "@/lib/utils/cn";

/**
 * The shared sticky app header for the signed-in surfaces (the /home hub, the
 * comp studio, the portfolio). Extracted from the near-identical headers that
 * used to live inline in comps/page.tsx and portfolio/page.tsx so the wordmark,
 * cross-nav, and <StudioAccountMenu/> can never drift apart.
 *
 * Server-safe: pure markup + <Link>s; the only interactive piece is
 * <StudioAccountMenu/>, itself a client component rendered as a child (the
 * server/RSC page shell stays intact). The wordmark links to /home — the hub is
 * the signed-in home base — and the nav marks the current surface.
 */
const NAV: { key: "home" | "studio" | "portfolio"; label: string; href: string }[] = [
  { key: "home", label: "Home", href: "/home" },
  { key: "studio", label: "Comp studio", href: "/comps" },
  { key: "portfolio", label: "Portfolio", href: "/portfolio" },
];

export function AppHeader({
  plan,
  pro,
  subscribed,
  name,
  active,
}: {
  plan: string;
  pro: boolean;
  subscribed: boolean;
  /** Account holder's name (or email) — passed straight to the account menu avatar. */
  name?: string;
  /** Which surface is current, so its nav item reads as active. */
  active?: "home" | "studio" | "portfolio";
}) {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-5 sm:px-8">
        <Link
          href="/home"
          className="rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--cb-ember)]"
          aria-label="compbird home"
        >
          <Wordmark />
        </Link>
        <div className="flex items-center gap-4 sm:gap-5">
          <nav aria-label="App" className="hidden items-center gap-4 sm:flex sm:gap-5">
            {NAV.map((item) => {
              const isActive = item.key === active;
              return (
                <Link
                  key={item.key}
                  href={item.href}
                  aria-current={isActive ? "page" : undefined}
                  className={cn(
                    "text-sm transition-colors hover:text-foreground",
                    isActive
                      ? "font-medium text-foreground"
                      : "text-muted-foreground",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <StudioAccountMenu plan={plan} pro={pro} subscribed={subscribed} name={name} />
        </div>
      </div>
    </header>
  );
}
