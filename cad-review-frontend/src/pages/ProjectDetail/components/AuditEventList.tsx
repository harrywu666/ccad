import { useEffect, useMemo, useRef } from 'react';
import { AlertCircle, CheckCircle2, Clock3, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { AuditEvent } from '@/types/api';

interface AuditEventListProps {
  events: AuditEvent[];
  loading?: boolean;
  error?: string;
}

const levelStyleMap = {
  info: {
    icon: RefreshCw,
    iconClassName: 'text-primary',
    boxClassName: 'bg-primary/10 border-primary/20',
    label: '进行中',
  },
  success: {
    icon: CheckCircle2,
    iconClassName: 'text-emerald-600',
    boxClassName: 'bg-emerald-50 border-emerald-200',
    label: '已完成',
  },
  warning: {
    icon: Clock3,
    iconClassName: 'text-amber-600',
    boxClassName: 'bg-amber-50 border-amber-200',
    label: '需注意',
  },
  error: {
    icon: AlertCircle,
    iconClassName: 'text-destructive',
    boxClassName: 'bg-destructive/10 border-destructive/20',
    label: '需要处理',
  },
} as const;

const formatTime = (value?: string | null) => {
  if (!value) return '--:--:--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--:--:--';
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
};

export default function AuditEventList({
  events,
  loading = false,
  error,
}: AuditEventListProps) {
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    list.scrollTop = list.scrollHeight;
  }, [events]);

  const content = useMemo(() => {
    if (!events.length) {
      return (
        <div className="flex min-h-[320px] items-center justify-center px-6 text-center text-[14px] leading-6 text-muted-foreground">
          审图启动后，系统会在这里持续更新进度。你可以最小化窗口，后台会继续运行。
        </div>
      );
    }

    return (
      <div className="space-y-3 p-4">
        {events.map((event) => {
          const style = levelStyleMap[event.level] || levelStyleMap.info;
          const Icon = style.icon;
          return (
            <div key={event.id} className="border border-border bg-white px-4 py-3">
              <div className="flex items-start gap-3">
                <div className={cn('mt-0.5 flex size-8 shrink-0 items-center justify-center border', style.boxClassName)}>
                  <Icon className={cn('size-4', style.iconClassName, event.level === 'info' ? 'animate-spin' : '')} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-[12px] font-medium text-muted-foreground">{style.label}</span>
                    <span className="shrink-0 text-[12px] text-muted-foreground">{formatTime(event.created_at)}</span>
                  </div>
                  <p className="mt-1 text-[14px] leading-6 text-foreground">{event.message}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    );
  }, [events]);

  return (
    <div
      className="flex min-h-0 flex-col overflow-hidden border border-border bg-white shadow-lg"
      style={{ height: 'min(680px, calc(100vh - 96px))' }}
    >
      <div className="border-b border-border px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-[18px] font-semibold text-foreground">实时进度日志</h3>
            <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
              系统会持续告诉你现在做到哪一步，长时间阶段也会定时更新。
            </p>
          </div>
          {loading ? <RefreshCw className="size-4 animate-spin text-muted-foreground" /> : null}
        </div>
        {error ? (
          <div className="mt-3 border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] leading-5 text-amber-700">
            暂时无法更新进度日志，后台仍可能在继续运行。
          </div>
        ) : null}
      </div>

      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto bg-secondary/15">
        {content}
      </div>
    </div>
  );
}
