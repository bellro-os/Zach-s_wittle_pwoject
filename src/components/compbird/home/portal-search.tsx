"use client";

import { useEffect, useRef } from "react";

/**
 * The hub's hero action — the instant-CMA entry. A plain GET form to /comps
 * (no typeahead): the studio reads ?address= as a deep link exactly the way the
 * landing hero's form feeds it, so the address-first → priced-report flow is
 * identical here. Bordered pill in the brand's search idiom; autofocused so a
 * signed-in agent can start typing the moment the hub paints.
 */
export function PortalSearch() {
  const inputRef = useRef<HTMLInputElement>(null);

  // Autofocus via effect (not the `autoFocus` attr) so it never fights SSR
  // hydration warnings and only fires once the field is interactive.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  return (
    <form
      action="/comps"
      method="GET"
      className="flex w-full max-w-2xl items-center gap-2 rounded-full border border-border bg-card p-1.5 pl-5 transition-colors duration-300 focus-within:border-[var(--cb-ember)]/50"
    >
      <input
        ref={inputRef}
        type="text"
        name="address"
        required
        autoComplete="street-address"
        placeholder="Enter any Virginia or D.C. address"
        aria-label="Property address"
        className="min-w-0 flex-1 bg-transparent text-[0.95rem] text-foreground placeholder:text-muted-foreground focus:outline-none"
      />
      <button
        type="submit"
        className="shrink-0 rounded-full bg-[var(--cb-ember)] px-5 py-2.5 text-sm font-semibold text-[var(--cb-on-ember)] shadow-[0_8px_30px_-8px_var(--cb-glow)] transition-colors duration-300 hover:bg-[var(--cb-ember-deep)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
      >
        Price it
      </button>
    </form>
  );
}
