import { Badge } from "@/components/ui/badge";
import { leadTypeLabel, leadTypeBadgeVariant } from "@/lib/data/lead-types";

export function LeadTypeBadge({
  leadType,
  title,
}: {
  leadType: string;
  title?: string;
}) {
  const variant = leadTypeBadgeVariant(leadType);
  return (
    <Badge variant={variant} title={title} className="cursor-help">
      {leadTypeLabel(leadType)}
    </Badge>
  );
}
