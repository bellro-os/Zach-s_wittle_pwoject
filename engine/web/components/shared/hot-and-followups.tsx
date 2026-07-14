import { Flame, Clock } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getHotAndFollowups } from "@/lib/data/quick-prospects";
import { daysSince } from "@/lib/utils";

interface Props {
  /** When set, scopes the section heading (e.g. "Hot prospects · pipeline"
   * for context). Optional; defaults to the standalone wording. */
  contextLabel?: string;
  /** Tighter padding + smaller fonts when shown on a busy inner page. */
  compact?: boolean;
}

/** Twin cards: hot prospects (last 30 days) + follow-ups due (next 3 days).
 * Server component — re-fetches on every render (revalidatePath triggered
 * by outcome logging keeps this fresh).
 *
 * Renders nothing when there's no data. */
export async function HotAndFollowupsBanner({ contextLabel, compact }: Props) {
  const { hot, due } = await getHotAndFollowups({ limit: compact ? 5 : 10 });
  if (hot.length === 0 && due.length === 0) return null;

  const titleSuffix = contextLabel ? (
    <span className="text-(--color-muted-foreground) font-normal text-xs ml-1">
      · {contextLabel}
    </span>
  ) : null;

  const pad = compact ? "p-3" : "p-4";
  const headingCls = compact
    ? "font-semibold text-sm mb-2 inline-flex items-center gap-2"
    : "font-semibold mb-2 inline-flex items-center gap-2";

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {hot.length > 0 && (
        <Card className={`${pad} border-l-4 border-(--color-success)`}>
          <h2 className={headingCls}>
            <Flame className="size-4 text-(--color-success)" />
            Hot prospects (last 30 days)
            {titleSuffix}
          </h2>
          <ul className="divide-y divide-(--color-border) text-sm">
            {hot.map((h) => {
              const ago = daysSince(h.timestamp);
              return (
                <li
                  key={h.id}
                  className="py-1.5 flex items-center justify-between gap-3"
                >
                  <span className="truncate min-w-0">
                    <strong>{h.owner || "—"}</strong>
                    {h.siteAddr ? ` · ${h.siteAddr}` : ""}
                  </span>
                  <Badge variant="success" className="text-[10px] shrink-0">
                    {h.outcome.replace(/_/g, " ")} · {ago}d
                  </Badge>
                </li>
              );
            })}
          </ul>
        </Card>
      )}
      {due.length > 0 && (
        <Card className={`${pad} border-l-4 border-(--color-warning)`}>
          <h2 className={headingCls}>
            <Clock className="size-4 text-(--color-warning)" />
            Follow-ups due (next 3 days)
            {titleSuffix}
          </h2>
          <ul className="divide-y divide-(--color-border) text-sm">
            {due.map((f) => (
              <li
                key={f.id}
                className="py-1.5 flex items-center justify-between gap-3"
              >
                <span className="truncate min-w-0">
                  <strong>{f.owner || "—"}</strong>
                  {f.siteAddr ? ` · ${f.siteAddr}` : ""}
                </span>
                <span className="text-xs text-(--color-muted-foreground) tabular-nums shrink-0">
                  {f.nextFollowup?.toISOString().slice(0, 10)}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
