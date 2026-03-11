import { Badge } from '@/components/ui/badge';

type FindingStatus = 'confirmed' | 'suspected' | 'needs_review' | null | undefined;

const STATUS_META: Record<Exclude<FindingStatus, null | undefined>, { label: string; className: string }> = {
  confirmed: {
    label: '已确认',
    className: 'rounded-none border-success/30 bg-success/10 text-success',
  },
  suspected: {
    label: '待复核',
    className: 'rounded-none border-amber-300 bg-amber-50 text-amber-700',
  },
  needs_review: {
    label: '待人工确认',
    className: 'rounded-none border-destructive/30 bg-destructive/10 text-destructive',
  },
};

interface FindingStatusBadgeProps {
  status?: FindingStatus;
  reviewRound?: number | null;
  sourceAgent?: string | null;
}

export default function FindingStatusBadge({
  status,
  reviewRound,
}: FindingStatusBadgeProps) {
  if (!status || !STATUS_META[status]) return null;

  const round = Number(reviewRound || 1);

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant="outline" className={STATUS_META[status].className}>
        {STATUS_META[status].label}
      </Badge>
      {round > 1 ? (
        <Badge variant="outline" className="rounded-none border-border bg-secondary/40 text-muted-foreground">
          已补图复核
        </Badge>
      ) : null}
    </div>
  );
}
