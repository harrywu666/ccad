import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  Bot,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Crown,
  Loader2,
  Minus,
  RefreshCw,
  Sparkles,
  TriangleAlert,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Dialog, DialogDescription, DialogOverlay, DialogPortal, DialogTitle } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { AuditEvent } from "@/types/api";
import AuditEventList from "./AuditEventList";
import type {
  ChiefCardViewModel,
  FinalReviewCardViewModel,
  OrganizerCardViewModel,
  WorkerSessionCardViewModel,
} from "./useAuditProgressViewModel";

interface AuditProgressDialogProps {
  open: boolean;
  progress: number;
  headline: string;
  supportingText: string;
  startedAt?: string | null;
  chief: ChiefCardViewModel;
  finalReview: FinalReviewCardViewModel;
  organizer: OrganizerCardViewModel;
  workerWall: {
    active: WorkerSessionCardViewModel[];
    recentCompleted: WorkerSessionCardViewModel[];
  };
  debugTimeline: {
    enabled: boolean;
    events: AuditEvent[];
  };
  eventError?: string;
  eventLoading?: boolean;
  providerLabel?: string;
  onMinimize: () => void;
  onRequestClose: (onStep: (step: string) => void) => Promise<void>;
  closeDisabled?: boolean;
}

type DrawerMode =
  | { type: "session"; session: WorkerSessionCardViewModel }
  | { type: "timeline" }
  | null;

function SummaryMetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="border border-border/70 bg-white px-4 py-4 shadow-[0_1px_0_rgba(0,0,0,0.02)]">
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">{label}</p>
      <p className="mt-3 text-[28px] font-semibold tracking-[-0.04em] text-foreground">{value}</p>
      <p className="mt-2 text-[12px] leading-5 text-muted-foreground">{hint}</p>
    </div>
  );
}

function StageStatusCard({
  title,
  icon,
  summary,
  currentAction,
  updatedAt,
  metrics,
  secondaryLabel,
}: {
  title: string;
  icon: ReactNode;
  summary: string;
  currentAction: string;
  updatedAt?: string | null;
  metrics: Array<{ label: string; value: string }>;
  secondaryLabel?: string | null;
}) {
  return (
    <section className="border border-border bg-white px-5 py-5 shadow-[0_1px_0_rgba(0,0,0,0.02)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center border border-primary/20 bg-primary/10 text-primary">
              {icon}
            </div>
            <div>
              <h3 className="text-[18px] font-semibold text-foreground">{title}</h3>
              <p className="mt-1 text-[13px] leading-6 text-muted-foreground">{summary}</p>
            </div>
          </div>
          <p className="mt-4 text-[16px] font-semibold leading-7 text-foreground">{currentAction}</p>
          {secondaryLabel ? (
            <p className="mt-2 text-[12px] leading-5 text-muted-foreground">{secondaryLabel}</p>
          ) : null}
        </div>
        {updatedAt ? (
          <span className="text-[11px] text-muted-foreground">最近更新 {formatEventClock(updatedAt)}</span>
        ) : null}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {metrics.map((metric) => (
          <span
            key={`${title}-${metric.label}`}
            className="rounded-full border border-border bg-secondary/20 px-3 py-1 text-[11px] font-medium text-foreground"
          >
            {metric.label} {metric.value}
          </span>
        ))}
      </div>
    </section>
  );
}

function formatEventClock(value?: string | null) {
  if (!value) return "--:--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--:--";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function resolveEventSessionKey(event: AuditEvent) {
  const meta = event.meta && typeof event.meta === "object" && !Array.isArray(event.meta) ? event.meta : {};
  const direct = typeof meta.session_key === "string" ? meta.session_key.trim() : "";
  if (direct) return direct;
  const artifactPath = typeof meta.artifact_path === "string" ? meta.artifact_path.trim() : "";
  const fileName = artifactPath.split("/").pop() || "";
  const sheetMatch = fileName.match(/sheet_semantic_([^_]+)__\d{8}/);
  if (sheetMatch) return `sheet_semantic:${sheetMatch[1]}`;
  const pairMatch = fileName.match(/pair_compare_([^_]+)_([^_]+)__\d{8}/);
  if (pairMatch) return `pair_compare:${pairMatch[1]}:${pairMatch[2]}`;
  return "";
}

function WorkerSessionCard({
  item,
  onOpenDetails,
}: {
  item: WorkerSessionCardViewModel;
  onOpenDetails: (session: WorkerSessionCardViewModel) => void;
}) {
  const contextBadges = [
    item.context.sheet_no ? `图纸 ${item.context.sheet_no}` : null,
    item.context.source_sheet_no && item.context.target_sheet_no
      ? `${item.context.source_sheet_no} ↔ ${item.context.target_sheet_no}`
      : null,
  ].filter(Boolean) as string[];

  return (
    <article
      className={cn(
        "border px-4 py-4 transition-colors",
        item.status === "active" && "border-primary/30 bg-primary/5",
        item.status === "completed" && "border-emerald-200 bg-emerald-50/60",
        item.status === "blocked" && "border-amber-200 bg-amber-50/70",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="text-[15px] font-semibold text-foreground">{item.workerName}</p>
          <p className="text-[12px] text-muted-foreground">{item.taskTitle}</p>
        </div>
        <Badge
          variant="outline"
          className={cn(
            "rounded-full px-2.5 py-1 text-[11px] font-medium",
            item.status === "active" && "border-primary/30 bg-white text-primary",
            item.status === "completed" && "border-emerald-300 bg-white text-emerald-700",
            item.status === "blocked" && "border-amber-300 bg-white text-amber-700",
          )}
        >
          {item.statusLabel}
        </Badge>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-border bg-white px-2.5 py-1 text-[11px] font-medium text-foreground">
          {item.skillLabel}
        </span>
        {contextBadges.map((badge) => (
          <span
            key={badge}
            className="rounded-full border border-border/80 bg-secondary/20 px-2.5 py-1 text-[11px] font-medium text-muted-foreground"
          >
            {badge}
          </span>
        ))}
        {item.updatedAt ? (
          <span className="text-[11px] text-muted-foreground">{formatEventClock(item.updatedAt)}</span>
        ) : null}
      </div>

      <p className="mt-4 text-[14px] font-medium leading-6 text-foreground">{item.currentAction}</p>

      <div className="mt-4 space-y-2 border-t border-border/70 pt-3">
        {item.recentActions.length ? item.recentActions.map((action, index) => (
          <div key={`${item.key}-${action.label}-${index}`} className="flex gap-3 text-[12px] leading-5 text-muted-foreground">
            <span className="w-[58px] shrink-0 font-medium text-foreground/75">{formatEventClock(action.at)}</span>
            <div className="min-w-0">
              <span className="mr-2 rounded-full border border-border bg-white px-2 py-0.5 text-[10px] font-medium text-foreground">
                {action.label}
              </span>
              <span>{action.text}</span>
            </div>
          </div>
        )) : (
          <p className="text-[12px] leading-5 text-muted-foreground">这张副审卡刚刚创建，尚未积累更多动作。</p>
        )}
      </div>

      <div className="mt-4 flex justify-end">
        <Button
          type="button"
          variant="ghost"
          onClick={() => onOpenDetails(item)}
          className="h-8 rounded-none px-2 text-[12px] font-medium text-foreground hover:bg-white"
        >
          查看详情
          <ChevronRight className="ml-1 h-3.5 w-3.5" />
        </Button>
      </div>
    </article>
  );
}

function DebugDrawer({
  mode,
  events,
  loading,
  error,
  onClose,
}: {
  mode: DrawerMode;
  events: AuditEvent[];
  loading?: boolean;
  error?: string;
  onClose: () => void;
}) {
  if (!mode) return null;

  const filteredEvents = mode.type === "timeline"
    ? events
    : events.filter((event) => resolveEventSessionKey(event) === mode.session.key);

  const title = mode.type === "timeline" ? "全部动作流" : `${mode.session.workerName} · ${mode.session.taskTitle}`;
  const description = mode.type === "timeline"
    ? "这里保留完整运行事件，主要用于调试和排障。"
    : `按会话 ${mode.session.key} 过滤的原始事件。`;

  return (
    <aside className="absolute inset-y-0 right-0 z-10 flex w-full max-w-[420px] flex-col border-l border-border bg-[#FBF9F3] shadow-[-18px_0_40px_rgba(15,23,42,0.08)]">
      <div className="border-b border-border bg-white px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-[16px] font-semibold text-foreground">{title}</h3>
            <p className="mt-1 text-[12px] leading-5 text-muted-foreground">{description}</p>
          </div>
          <Button
            type="button"
            variant="ghost"
            onClick={onClose}
            className="h-8 rounded-none px-2 text-muted-foreground hover:bg-secondary/30"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden px-4 py-4 [&>div]:h-full">
        <AuditEventList events={filteredEvents} error={error} loading={loading} />
      </div>
    </aside>
  );
}

export function getAuditProviderLabel(_value?: string | null) {
  const value = String(_value || "").trim().toLowerCase();
  if (value === "sdk" || value === "kimi_sdk") return "Kimi SDK";
  if (value === "cli") return "Kimi CLI";
  if (value === "auto") return "自动选择";
  return "OpenRouter";
}

export function formatAuditElapsedText(startedAt?: string | null, now = new Date()) {
  if (!startedAt) return "已运行 --:--";
  const started = new Date(startedAt);
  if (Number.isNaN(started.getTime())) return "已运行 --:--";
  const diffSeconds = Math.max(0, Math.floor((now.getTime() - started.getTime()) / 1000));
  const hours = Math.floor(diffSeconds / 3600);
  const minutes = Math.floor((diffSeconds % 3600) / 60);
  const seconds = diffSeconds % 60;
  if (hours > 0) {
    return `已运行 ${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `已运行 ${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function AuditProgressPill({
  progress,
  onClick,
}: {
  progress: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex h-auto items-center gap-3 border border-border bg-secondary px-3 py-2 text-left text-[13px] font-medium text-foreground transition-colors hover:bg-secondary/80"
    >
      <RefreshCw className="h-3.5 w-3.5 animate-spin text-primary" />
      <div className="min-w-0 truncate">审图内核调度中</div>
      <span className="text-muted-foreground">{Math.round(progress)}%</span>
    </button>
  );
}

export default function AuditProgressDialog({
  open,
  progress,
  headline,
  supportingText,
  startedAt,
  chief,
  finalReview,
  organizer,
  workerWall,
  debugTimeline,
  eventError,
  eventLoading = false,
  providerLabel,
  onMinimize,
  onRequestClose,
  closeDisabled = false,
}: AuditProgressDialogProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [shuttingDown, setShuttingDown] = useState(false);
  const [shutdownStep, setShutdownStep] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const [drawerMode, setDrawerMode] = useState<DrawerMode>(null);
  const elapsedText = useMemo(() => formatAuditElapsedText(startedAt, new Date(now)), [startedAt, now]);

  useEffect(() => {
    if (!open) return;
    setNow(Date.now());
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [open, startedAt]);

  useEffect(() => {
    if (!open) {
      setDrawerMode(null);
    }
  }, [open]);

  const handleConfirmClose = async () => {
    setConfirmOpen(false);
    setShuttingDown(true);
    setShutdownStep("正在发送终止信号...");
    try {
      await onRequestClose((step) => setShutdownStep(step));
    } finally {
      setShuttingDown(false);
      setShutdownStep("");
    }
  };

  return (
    <>
      <AlertDialog open={confirmOpen} onOpenChange={(next) => !shuttingDown && setConfirmOpen(next)}>
        <AlertDialogContent className="max-w-[520px] rounded-none border border-border bg-white p-0 shadow-lg">
          <AlertDialogHeader className="items-start gap-4 px-7 pt-7 text-left">
            <div className="flex size-11 items-center justify-center rounded-none bg-red-50 text-red-600">
              <TriangleAlert className="size-5" />
            </div>
            <div className="space-y-2">
              <AlertDialogTitle className="text-[22px] font-semibold leading-none text-zinc-900">
                终止审图进程？
              </AlertDialogTitle>
              <AlertDialogDescription className="text-[14px] leading-6 text-zinc-600">
                确认后将立即中断后台审图任务，并清空本次审图产生的所有缓存数据。此操作不可撤销，如需保留进度请点击最小化。
              </AlertDialogDescription>
            </div>
          </AlertDialogHeader>
          <AlertDialogFooter className="mt-7 flex-row justify-end gap-3 border-t border-zinc-100 px-7 py-5">
            <AlertDialogCancel className="rounded-none">
              最小化继续跑
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); void handleConfirmClose(); }}
              className="rounded-none bg-destructive hover:bg-destructive/90"
            >
              确认终止
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={open} onOpenChange={() => undefined}>
        <DialogPortal>
          <DialogOverlay className="bg-black/35" />
          <DialogPrimitive.Content
            onEscapeKeyDown={(event) => event.preventDefault()}
            onInteractOutside={(event) => event.preventDefault()}
            className="fixed inset-4 z-50 flex min-h-0 flex-col overflow-hidden border border-border bg-[#F7F4EE] p-0 outline-none"
          >
            {shuttingDown ? (
              <div className="px-8 py-12">
                <div className="mx-auto max-w-[480px] text-center">
                  <div className="mx-auto mb-6 flex size-14 items-center justify-center bg-destructive/10">
                    <Loader2 className="size-7 animate-spin text-destructive" />
                  </div>
                  <DialogTitle className="text-[24px] font-semibold tracking-tight text-foreground">
                    正在终止审图
                  </DialogTitle>
                  <DialogDescription className="mt-3 text-[14px] leading-6 text-muted-foreground">
                    系统正在安全关闭后台审图进程并清理缓存数据，请稍等片刻...
                  </DialogDescription>
                  <div className="mt-8 border border-border bg-secondary/20 px-6 py-5">
                    <div className="flex items-center justify-center gap-3">
                      <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" />
                      <span className="text-[14px] font-medium text-foreground">{shutdownStep}</span>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="relative flex min-h-0 flex-1 flex-col">
                <div className="border-b border-border bg-[#FFFDF8] px-8 py-6">
                  <div className="flex items-start justify-between gap-6">
                    <div className="min-w-0 space-y-4">
                      <div className="flex items-center gap-3">
                        <div className="flex size-11 items-center justify-center border border-primary/20 bg-primary/10 text-primary">
                          <Crown className="size-5" />
                        </div>
                        <div>
                          <DialogTitle className="text-[30px] font-semibold tracking-[-0.05em] text-foreground">
                            审图内核 + 副审实时现场
                          </DialogTitle>
                          <DialogDescription className="mt-1 max-w-[760px] text-[14px] leading-6 text-muted-foreground">
                            {supportingText || "审图内核负责调度与收束，副审卡墙实时回放各个会话正在做的事。"}
                          </DialogDescription>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-3 text-[13px]">
                        <span className="rounded-full border border-border bg-white px-3 py-1.5 font-medium text-foreground">
                          当前焦点：{headline}
                        </span>
                        {providerLabel ? (
                          <span className="rounded-full border border-border bg-white px-3 py-1.5 font-medium text-foreground">
                            本轮引擎：{providerLabel}
                          </span>
                        ) : null}
                        <span className="rounded-full border border-border bg-white px-3 py-1.5 font-medium text-foreground">
                          {elapsedText}
                        </span>
                        <span className="rounded-full border border-border bg-white px-3 py-1.5 font-medium text-muted-foreground">
                          活跃副审 {chief.activeWorkerCount}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      {debugTimeline.enabled ? (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => setDrawerMode({ type: "timeline" })}
                          className="h-10 rounded-none border-border bg-white px-4 text-[14px] font-medium shadow-none hover:bg-secondary hover:shadow-none"
                        >
                          <Bot className="mr-2 h-4 w-4" />
                          全部动作
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        variant="outline"
                        onClick={onMinimize}
                        className="h-10 rounded-none border-border bg-white px-4 text-[14px] font-medium shadow-none hover:bg-secondary hover:shadow-none"
                      >
                        <Minus className="mr-2 h-4 w-4" />
                        最小化
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => setConfirmOpen(true)}
                        disabled={closeDisabled}
                        className="h-10 rounded-none border-border bg-white px-4 text-[14px] font-medium text-destructive shadow-none hover:bg-destructive/10 hover:text-destructive hover:shadow-none disabled:text-muted-foreground"
                      >
                        <X className="mr-2 h-4 w-4" />
                        关闭
                      </Button>
                    </div>
                  </div>
                </div>

                <div className={cn("min-h-0 flex-1 overflow-y-auto px-8 py-6", drawerMode && "pr-[444px]")}>
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
                    <SummaryMetricCard
                      label="已派任务"
                      value={String(chief.assignedTaskCount)}
                      hint="审图内核已经明确派出去的副审会话数量。"
                    />
                    <SummaryMetricCard
                      label="活跃副审"
                      value={String(chief.activeWorkerCount)}
                      hint="当前仍在执行中的副审会话。"
                    />
                    <SummaryMetricCard
                      label="最近完成"
                      value={String(chief.completedWorkerCount)}
                      hint="已完成并回流审图内核的副审会话总数。"
                    />
                    <SummaryMetricCard
                      label="阻塞"
                      value={String(chief.blockedWorkerCount)}
                      hint="需要重试或审图内核介入的会话数量。"
                    />
                    <SummaryMetricCard
                      label="待启动"
                      value={String(chief.queuedTaskCount)}
                      hint="审图内核已经规划但还没真正启动的任务。"
                    />
                    <SummaryMetricCard
                      label="已发现问题"
                      value={String(chief.issueCount)}
                      hint="当前累计沉淀的问题数。"
                    />
                  </div>

                  <div className="mt-4 border border-border bg-[#FFFDF8] px-5 py-5 shadow-[0_1px_0_rgba(0,0,0,0.02)]">
                    <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-3">
                          <div className="flex size-10 items-center justify-center border border-primary/20 bg-primary/10 text-primary">
                            <Sparkles className="size-4" />
                          </div>
                          <div>
                            <h3 className="text-[18px] font-semibold text-foreground">审图内核总控卡</h3>
                            <p className="mt-1 text-[13px] leading-6 text-muted-foreground">
                              {chief.summary}
                            </p>
                          </div>
                        </div>
                        <p className="mt-4 text-[22px] font-semibold leading-8 tracking-[-0.04em] text-foreground">
                          {chief.currentAction}
                        </p>
                      </div>

                      <div className="w-full max-w-[320px] border border-border bg-white px-4 py-4">
                        <div className="flex items-center gap-2">
                          <Clock3 className="size-4 text-primary" />
                          <p className="text-[13px] font-semibold text-foreground">总进度</p>
                        </div>
                        <div className="mt-4">
                          <div className="flex items-center justify-between text-[12px] text-muted-foreground">
                            <span>审图推进</span>
                            <span>{Math.round(progress)}%</span>
                          </div>
                          <Progress
                            value={progress}
                            className="mt-2 h-2 rounded-none bg-secondary [&>div]:bg-primary"
                          />
                        </div>
                        {chief.updatedAt ? (
                          <p className="mt-4 text-[12px] leading-5 text-muted-foreground">
                            最近更新 {formatEventClock(chief.updatedAt)}
                          </p>
                        ) : null}
                      </div>
                    </div>
                  </div>

                  <section className="mt-4 border border-border bg-white px-5 py-5 shadow-[0_1px_0_rgba(0,0,0,0.02)]">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h3 className="text-[18px] font-semibold text-foreground">副审实时卡墙</h3>
                        <p className="mt-1 text-[13px] leading-6 text-muted-foreground">
                          一张卡绑定一张 assignment，卡内可以有多次 Skill 动作，但不会再膨胀出新的前台卡片。
                        </p>
                      </div>
                      <span className="rounded-full border border-border bg-secondary/30 px-3 py-1 text-[11px] font-medium text-muted-foreground">
                        当前显示 {workerWall.active.length} 张
                      </span>
                    </div>

                    <div className="mt-4 grid gap-4 grid-cols-1 md:grid-cols-2 xl:[grid-template-columns:repeat(auto-fit,minmax(320px,1fr))]">
                      {workerWall.active.length ? workerWall.active.map((item) => (
                        <WorkerSessionCard
                          key={item.key}
                          item={item}
                          onOpenDetails={(session) => setDrawerMode({ type: "session", session })}
                        />
                      )) : (
                        <div className="border border-dashed border-border bg-secondary/20 px-4 py-5 text-[13px] leading-6 text-muted-foreground">
                          当前没有活跃副审，审图内核可能还在准备任务，或者上一批已经回流等待汇总。
                        </div>
                      )}
                    </div>
                  </section>

                  <div className="mt-4 grid gap-4 xl:grid-cols-2">
                    <StageStatusCard
                      title="终审复核"
                      icon={<Bot className="size-4" />}
                      summary={finalReview.summary}
                      currentAction={finalReview.currentAction}
                      updatedAt={finalReview.updatedAt}
                      secondaryLabel={finalReview.currentAssignmentTitle || null}
                      metrics={[
                        { label: "已放行", value: String(finalReview.acceptedCount) },
                        { label: "补证据", value: String(finalReview.needsMoreEvidenceCount) },
                        { label: "补派单", value: String(finalReview.redispatchCount) },
                      ]}
                    />
                    <StageStatusCard
                      title="汇总整理"
                      icon={<Sparkles className="size-4" />}
                      summary={organizer.summary}
                      currentAction={organizer.currentAction}
                      updatedAt={organizer.updatedAt}
                      secondaryLabel={organizer.currentSection || null}
                      metrics={[
                        { label: "已通过问题", value: String(organizer.acceptedIssueCount) },
                        { label: "当前章节", value: organizer.currentSection || '待生成' },
                      ]}
                    />
                  </div>

                  <section className="mt-4 border border-border bg-white px-5 py-5 shadow-[0_1px_0_rgba(0,0,0,0.02)]">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="size-4 text-emerald-600" />
                      <h3 className="text-[18px] font-semibold text-foreground">最近完成</h3>
                    </div>
                    <p className="mt-1 text-[13px] leading-6 text-muted-foreground">
                      这里只保留少量最近完成的副审卡，避免已完成历史淹没现场信息。
                    </p>
                    <div className="mt-4 grid gap-4 grid-cols-1 md:grid-cols-2 xl:[grid-template-columns:repeat(auto-fit,minmax(320px,1fr))]">
                      {workerWall.recentCompleted.length ? workerWall.recentCompleted.map((item) => (
                        <WorkerSessionCard
                          key={item.key}
                          item={item}
                          onOpenDetails={(session) => setDrawerMode({ type: "session", session })}
                        />
                      )) : (
                        <div className="border border-dashed border-border bg-secondary/20 px-4 py-5 text-[13px] leading-6 text-muted-foreground">
                          还没有完成态副审回流到这里。
                        </div>
                      )}
                    </div>
                  </section>
                </div>

                <DebugDrawer
                  mode={drawerMode}
                  events={debugTimeline.events}
                  loading={eventLoading}
                  error={eventError}
                  onClose={() => setDrawerMode(null)}
                />
              </div>
            )}
          </DialogPrimitive.Content>
        </DialogPortal>
      </Dialog>
    </>
  );
}
