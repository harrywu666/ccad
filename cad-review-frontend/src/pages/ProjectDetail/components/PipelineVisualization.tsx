import {
  Boxes,
  Check,
  CircleDashed,
  Database,
  FileText,
  Link2,
  Map,
  Ruler,
  Scale,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type { AuditPipelineItem } from './useAuditProgressViewModel';

const stepIconMap = {
  prepare: Database,
  context: FileText,
  relationship_discovery: Link2,
  task_planning: Map,
  index: Ruler,
  dimension: Scale,
  material: Boxes,
} as const;

export default function PipelineVisualization({
  items,
}: {
  items: AuditPipelineItem[];
}) {
  return (
    <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {items.map((item, index) => {
        const Icon = stepIconMap[item.stepKey as keyof typeof stepIconMap] || CircleDashed;
        return (
          <li
            key={item.stepKey}
            className={cn(
              'min-h-[124px] border px-3 py-3 transition-colors',
              item.state === 'current' && 'border-primary bg-primary/5',
              item.state === 'complete' && 'border-emerald-200 bg-emerald-50/60',
              item.state === 'pending' && 'border-border bg-white',
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="space-y-2">
                <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <div className="flex items-center gap-2">
                  <Icon
                    className={cn(
                      'h-4 w-4',
                      item.state === 'current' && 'text-primary',
                      item.state === 'complete' && 'text-emerald-600',
                      item.state === 'pending' && 'text-muted-foreground',
                    )}
                  />
                  <h4 className="text-[13px] font-semibold text-foreground">{item.title}</h4>
                </div>
              </div>
              <div
                className={cn(
                  'flex h-5 w-5 items-center justify-center border text-[11px]',
                  item.state === 'current' && 'border-primary bg-primary text-white',
                  item.state === 'complete' && 'border-emerald-600 bg-emerald-600 text-white',
                  item.state === 'pending' && 'border-border bg-secondary text-muted-foreground',
                )}
                aria-label={`${item.title}-${item.state}`}
              >
                {item.state === 'complete' ? <Check className="h-3.5 w-3.5" /> : null}
                {item.state === 'current' ? <span>•</span> : null}
                {item.state === 'pending' ? <span>·</span> : null}
              </div>
            </div>

            <p className="mt-2 text-[11px] leading-5 text-muted-foreground">
              {item.description}
            </p>

            {item.issueCount !== null ? (
              <p className="mt-2 text-[11px] font-medium text-foreground">
                发现 {item.issueCount} 处问题
              </p>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
