"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Phone,
  Briefcase,
  Users,
  Search,
  Activity,
  Menu,
  Keyboard,
  Clock,
  TrendingUp,
  MapPin,
  Bookmark,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Logo } from "@/components/ratified-ui";
import {
  Sheet,
  SheetContent,
  SheetTrigger,
  SheetTitle,
  SheetClose,
} from "@/components/ui/sheet";

const LINKS = [
  { href: "/", label: "Queue", icon: Phone },
  { href: "/expired", label: "Expired", icon: Clock },
  { href: "/pipeline", label: "Pipeline", icon: Briefcase },
  { href: "/analytics", label: "Analytics", icon: TrendingUp },
  { href: "/neighborhoods", label: "Neighborhoods", icon: MapPin },
  { href: "/searches", label: "Searches", icon: Bookmark },
  { href: "/clients", label: "Clients", icon: Users },
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/search", label: "Search", icon: Search },
];

export function Nav() {
  const pathname = usePathname();

  function isActive(href: string) {
    return href === "/" ? pathname === "/" : pathname.startsWith(href);
  }

  return (
    <header className="sticky top-0 z-30 border-b border-white/10 bg-ink-950/80 backdrop-blur supports-[backdrop-filter]:bg-ink-950/60 no-print">
      <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-3 md:gap-6 px-4 md:px-5">
        {/* Mobile hamburger */}
        <Sheet>
          <SheetTrigger asChild>
            <button
              type="button"
              aria-label="Open menu"
              className="md:hidden inline-flex items-center justify-center size-9 rounded-full border border-white/10 text-slate-300 hover:border-emerald-500/25 hover:bg-emerald-500/10 hover:text-emerald-200"
            >
              <Menu className="size-4" />
            </button>
          </SheetTrigger>
          <SheetContent side="left">
            <SheetTitle>Realtor</SheetTitle>
            <nav className="flex flex-col gap-1 mt-2">
              {LINKS.map((l) => {
                const Icon = l.icon;
                return (
                  <SheetClose asChild key={l.href}>
                    <Link
                      href={l.href}
                      className={cn(
                        "inline-flex items-center gap-2 rounded-full px-3 py-2 text-sm transition-colors",
                        isActive(l.href)
                          ? "border border-emerald-500/25 bg-emerald-500/10 text-emerald-300 font-medium"
                          : "text-slate-300 hover:bg-white/5 hover:text-white",
                      )}
                    >
                      <Icon className="size-4" />
                      {l.label}
                    </Link>
                  </SheetClose>
                );
              })}
            </nav>
          </SheetContent>
        </Sheet>

        <Link
          href="/"
          className="flex items-center gap-2 font-semibold tracking-tight text-white"
        >
          <Logo className="size-7" />
          <span className="hidden sm:inline">Realtor</span>
        </Link>

        {/* Desktop nav */}
        <nav className="hidden md:flex items-center gap-1 text-sm">
          {LINKS.map((l) => {
            const Icon = l.icon;
            return (
              <Link
                key={l.href}
                href={l.href}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 transition-colors",
                  isActive(l.href)
                    ? "border border-emerald-500/25 bg-emerald-500/10 text-emerald-300 font-medium"
                    : "text-slate-400 hover:text-white hover:bg-white/5",
                )}
              >
                <Icon className="size-3.5" />
                {l.label}
              </Link>
            );
          })}
        </nav>

        <form action="/search" className="ml-auto hidden sm:block">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              name="q"
              placeholder="Address, owner, client..."
              className="h-8 w-48 lg:w-72 rounded-full border border-white/10 bg-white/[0.03] pl-8 pr-3 text-sm text-white placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60 focus-visible:border-emerald-500/25"
            />
          </div>
        </form>

        <button
          type="button"
          aria-label="Keyboard shortcuts"
          onClick={() =>
            window.dispatchEvent(new CustomEvent("keyboard-help-open"))
          }
          className="hidden md:inline-flex items-center justify-center size-9 rounded-full text-slate-400 hover:bg-emerald-500/10 hover:text-emerald-200"
          title="Keyboard shortcuts (?)"
        >
          <Keyboard className="size-4" />
        </button>
      </div>
    </header>
  );
}
