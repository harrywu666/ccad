import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  Bot,
  CheckCircle2,
  Clock3,
  Crown,
  Loader2,
  Minus,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  TriangleAlert,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
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
  AuditChiefSummaryViewModel,
  AuditPipelineItem,
  AuditResultLedgerViewModel,
  AuditWorkerTaskCardViewModel,
} from "./useAuditProgressViewModel";

interface AuditProgressDialogProps {
  open: boolean;
  progress: number;
  headline: string;
  supportingText: string;
  startedAt?: string | null;
  pipeline?: AuditPipelineItem[];
  chief: AuditChiefSummaryViewModel;
  workerBoard: {
    running: AuditWorkerTaskCardViewModel[];
    completed: AuditWorkerTaskCardViewModel[];
    blocked: AuditWorkerTaskCardViewModel[];
    queuedCount: number;
  };
  resultLedger: AuditResultLedgerViewModel;
  activeAgentName?: string;
  activeAgentMessage?: string;
  totalIssues?: number;
  events: AuditEvent[];
  eventError?: string;
  eventLoading?: boolean;
  providerLabel?: string;
  onMinimize: () => void;
  onRequestClose: (onStep: (step: string) => void) => Promise<void>;
  closeDisabled?: boolean;
}

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

function WorkerTaskCard({
  item,
}: {
  item: AuditWorkerTaskCardViewModel;
}) {
  return (
    <article
      className={cn(
        "border px-4 py-4 transition-colors",
        item.status === "running" && "border-primary/30 bg-primary/5",
        item.status === "completed" && "border-emerald-200 bg-emerald-50/60",
        item.status === "blocked" && "border-amber-200 bg-amber-50/70",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="text-[15px] font-semibold text-foreground">{item.title}</p>
          <p className="text-[12px] text-muted-foreground">{item.agentName}</p>
        </div>
        <Badge
          variant="outline"
          className={cn(
            "rounded-full px-2.5 py-1 text-[11px] font-medium",
            item.status === "running" && "border-primary/30 bg-white text-primary",
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
        {item.updatedAt ? (
          <span className="text-[11px] text-muted-foreground">{formatEventClock(item.updatedAt)}</span>
        ) : null}
      </div>

      <p className="mt-3 text-[13px] leading-6 text-muted-foreground">{item.summary}</p>
    </article>
  );
}

function WorkerLane({
  title,
  count,
  description,
  children,
  tone = "default",
}: {
  title: string;
  count: number;
  description: string;
  children: ReactNode;
  tone?: "default" | "active" | "review" | "complete";
}) {
  return (
    <section
      className={cn(
        "border px-4 py-4",
        tone === "active" && "border-primary/30 bg-primary/5",
        tone === "review" && "border-amber-200 bg-amber-50/40",
        tone === "complete" && "border-emerald-200 bg-emerald-50/40",
        tone === "default" && "border-border bg-white",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h4 className="text-[15px] font-semibold text-foreground">{title}</h4>
          <p className="mt-1 text-[12px] leading-5 text-muted-foreground">{description}</p>
        </div>
        <span className="rounded-full border border-border bg-white px-2.5 py-1 text-[11px] font-medium text-foreground">
          {count}
        </span>
      </div>
      <div className="mt-4 space-y-3">{children}</div>
    </section>
  );
}

function PipelineStrip({
  items,
}: {
  items: AuditPipelineItem[];
}) {
  if (!items.length) return null;
  return (
    <div className="border border-border bg-white px-4 py-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h4 className="text-[15px] font-semibold text-foreground">全局阶段带</h4>
          <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
            这里保留粗粒度阶段，只用来说明主流程走到哪一步。
          </p>
        </div>
        <span className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">主流程</span>
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {items.map((item) => (
          <div
            key={item.stepKey}
            className={cn(
              "border px-3 py-3",
              item.state === "current" && "border-primary/30 bg-primary/5",
              item.state === "complete" && "border-emerald-200 bg-emerald-50/60",
              item.state === "pending" && "border-border bg-secondary/20",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <p className="text-[13px] font-semibold text-foreground">{item.title}</p>
              <span className="text-[11px] text-muted-foreground">
                {item.state === "complete" ? "完成" : item.state === "current" ? "当前" : "待执行"}
              </span>
            </div>
            <p className="mt-2 text-[11px] leading-5 text-muted-foreground">{item.description}</p>
          </div>
        ))}
      </div>
    </div>
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
      <div className="min-w-0 truncate">主审调度中</div>
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
  pipeline = [],
  chief,
  workerBoard,
  resultLedger,
  activeAgentName,
  activeAgentMessage,
  totalIssues = 0,
  events,
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
  const latestEvent = useMemo(() => events[events.length - 1] ?? null, [events]);
  const latestRunnerBroadcast = useMemo(
    () => [...events].reverse().find((event) => event.event_kind === "runner_broadcast") ?? null,
    [events],
  );
  const elapsedText = useMemo(() => formatAuditElapsedText(startedAt, new Date(now)), [startedAt, now]);
  const focusAgentName = activeAgentName || latestRunnerBroadcast?.agent_name || latestEvent?.agent_name || headline;
  const activeSummary = activeAgentMessage || latestRunnerBroadcast?.message || latestEvent?.message || chief.bottleneck || supportingText;

  useEffect(() => {
    if (!open) return;
    setNow(Date.now());
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [open, startedAt]);

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
              <>
                <div className="border-b border-border bg-[#FFFDF8] px-8 py-6">
                  <div className="flex items-start justify-between gap-6">
                    <div className="min-w-0 space-y-4">
                      <div className="flex items-center gap-3">
                        <div className="flex size-11 items-center justify-center border border-primary/20 bg-primary/10 text-primary">
                          <Crown className="size-5" />
                        </div>
                        <div>
                          <DialogTitle className="text-[30px] font-semibold tracking-[-0.05em] text-foreground">
                            主审正在组织副审审图
                          </DialogTitle>
                          <DialogDescription className="mt-1 max-w-[760px] text-[14px] leading-6 text-muted-foreground">
                            {supportingText || "你看到的是本轮真实调度现场：主审在分派任务，副审在逐张图执行，结果会持续回流到这里。"}
                          </DialogDescription>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-3 text-[13px]">
                        <span className="rounded-full border border-border bg-white px-3 py-1.5 font-medium text-foreground">
                          当前焦点：{focusAgentName}
                        </span>
                        {providerLabel ? (
                          <span className="rounded-full border border-border bg-white px-3 py-1.5 font-medium text-foreground">
                            本轮引擎：{providerLabel}
                          </span>
                        ) : null}
                        <span className="rounded-full border border-border bg-white px-3 py-1.5 font-medium text-foreground">
                          {elapsedText}
                        </span>
                        {latestEvent?.event_kind === "heartbeat" ? (
                          <span className="rounded-full border border-border bg-white px-3 py-1.5 font-medium text-muted-foreground">
                            当前仍在稳定推进
                          </span>
                        ) : null}
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
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

                <div className="grid min-h-0 flex-1 gap-0 xl:grid-cols-[minmax(0,1.45fr)_360px]">
                  <div className="min-h-0 overflow-y-auto px-8 py-6">
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                      <SummaryMetricCard
                        label="怀疑卡"
                        value={String(chief.hypothesisCount)}
                        hint="主审先形成待核对怀疑，再决定要不要派副审。"
                      />
                      <SummaryMetricCard
                        label="已派副审"
                        value={String(chief.plannedTaskCount)}
                        hint="这轮已经真正生成出来的副审任务卡数量。"
                      />
                      <SummaryMetricCard
                        label="处理中"
                        value={String(chief.runningTaskCount)}
                        hint="当前已经被调起、正在跑模型或整理结果的副审任务。"
                      />
                      <SummaryMetricCard
                        label="已收束"
                        value={String(chief.completedTaskCount)}
                        hint="已经拿到稳定输出、等待主审消化的副审任务。"
                      />
                      <SummaryMetricCard
                        label="已发现问题"
                        value={String(totalIssues)}
                        hint="已落到结果台账里的问题数，会继续增长。"
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
                              <h3 className="text-[18px] font-semibold text-foreground">主审指挥台</h3>
                              <p className="mt-1 text-[13px] leading-6 text-muted-foreground">
                                {chief.summary}
                              </p>
                            </div>
                          </div>
                          <p className="mt-4 text-[22px] font-semibold leading-8 tracking-[-0.04em] text-foreground">
                            {chief.currentAction || headline}
                          </p>
                          <p className="mt-3 text-[14px] leading-7 text-muted-foreground">
                            {activeSummary}
                          </p>
                        </div>

                        <div className="w-full max-w-[320px] border border-border bg-white px-4 py-4">
                          <div className="flex items-center gap-2">
                            <Bot className="size-4 text-primary" />
                            <p className="text-[13px] font-semibold text-foreground">当前瓶颈</p>
                          </div>
                          <p className="mt-3 text-[13px] leading-6 text-muted-foreground">
                            {chief.bottleneck}
                          </p>
                          <div className="mt-4">
                            <div className="flex items-center justify-between text-[12px] text-muted-foreground">
                              <span>总进度（粗略）</span>
                              <span>{Math.round(progress)}%</span>
                            </div>
                            <Progress
                              value={progress}
                              className="mt-2 h-2 rounded-none bg-secondary [&>div]:bg-primary"
                            />
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="mt-4 border border-border bg-white px-5 py-5 shadow-[0_1px_0_rgba(0,0,0,0.02)]">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <h3 className="text-[18px] font-semibold text-foreground">副审任务墙</h3>
                          <p className="mt-1 text-[13px] leading-6 text-muted-foreground">
                            这里展示已经被调起的真实副审任务，能看到它在审哪些图、调用了什么 skill、现在走到哪一步。
                          </p>
                        </div>
                        <span className="rounded-full border border-border bg-secondary/30 px-3 py-1 text-[11px] font-medium text-muted-foreground">
                          主审已派 {chief.plannedTaskCount} 张
                        </span>
                      </div>

                      <div className="mt-4 grid gap-4 xl:grid-cols-3">
                        <WorkerLane
                          title="处理中"
                          count={workerBoard.running.length}
                          description="已经被调起，正在跑模型、流式输出或整理结果。"
                          tone="active"
                        >
                          {workerBoard.running.length ? workerBoard.running.map((item) => (
                            <WorkerTaskCard key={item.key} item={item} />
                          )) : (
                            <div className="border border-dashed border-border bg-secondary/20 px-4 py-5 text-[13px] leading-6 text-muted-foreground">
                              当前没有活跃副审，主审可能正在准备下一批任务。
                            </div>
                          )}
                        </WorkerLane>

                        <WorkerLane
                          title="待调度"
                          count={workerBoard.queuedCount}
                          description="已经被主审纳入本轮计划，但还没真正调起执行。"
                          tone="default"
                        >
                          {workerBoard.queuedCount > 0 ? (
                            <div className="border border-dashed border-border bg-secondary/20 px-4 py-5">
                              <div className="flex items-center gap-2">
                                <Clock3 className="size-4 text-muted-foreground" />
                                <p className="text-[14px] font-semibold text-foreground">
                                  还有 {workerBoard.queuedCount} 张副审任务在排队
                                </p>
                              </div>
                              <p className="mt-3 text-[13px] leading-6 text-muted-foreground">
                                这通常意味着前面几张图的带图调用还没收束，主审会在它们回流后继续放下一批。
                              </p>
                            </div>
                          ) : (
                            <div className="border border-dashed border-border bg-secondary/20 px-4 py-5 text-[13px] leading-6 text-muted-foreground">
                              当前没有待调度任务，说明主审已经把已知任务都放出去了。
                            </div>
                          )}
                        </WorkerLane>

                        <WorkerLane
                          title="已收束 / 待处理"
                          count={workerBoard.completed.length + workerBoard.blocked.length}
                          description="这里放已经拿到输出的副审，以及需要重试或人工关注的任务。"
                          tone={workerBoard.blocked.length > 0 ? "review" : "complete"}
                        >
                          {workerBoard.blocked.map((item) => (
                            <WorkerTaskCard key={item.key} item={item} />
                          ))}
                          {workerBoard.completed.map((item) => (
                            <WorkerTaskCard key={item.key} item={item} />
                          ))}
                          {!workerBoard.completed.length && !workerBoard.blocked.length ? (
                            <div className="border border-dashed border-border bg-secondary/20 px-4 py-5 text-[13px] leading-6 text-muted-foreground">
                              还没有副审完成收束，主审结果台账稍后会在这里明显长出来。
                            </div>
                          ) : null}
                        </WorkerLane>
                      </div>
                    </div>

                    <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
                      <PipelineStrip items={pipeline} />

                      <div className="border border-border bg-white px-4 py-4">
                        <div className="flex items-center gap-2">
                          <ShieldAlert className="size-4 text-primary" />
                          <h4 className="text-[15px] font-semibold text-foreground">结果台账</h4>
                        </div>
                        <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                          这里不看原始事件，直接看这轮审图最后对你有用的收束状态。
                        </p>
                        <div className="mt-4 space-y-3">
                          <div className="flex items-center justify-between border border-border bg-secondary/20 px-3 py-3">
                            <span className="text-[12px] text-muted-foreground">已确认问题</span>
                            <span className="text-[18px] font-semibold text-foreground">{resultLedger.issueCount}</span>
                          </div>
                          <div className="flex items-center justify-between border border-border bg-secondary/20 px-3 py-3">
                            <span className="text-[12px] text-muted-foreground">已收束副审</span>
                            <span className="text-[18px] font-semibold text-foreground">{resultLedger.completedTaskCount}</span>
                          </div>
                          <div className="flex items-center justify-between border border-border bg-secondary/20 px-3 py-3">
                            <span className="text-[12px] text-muted-foreground">处理中副审</span>
                            <span className="text-[18px] font-semibold text-foreground">{resultLedger.runningTaskCount}</span>
                          </div>
                          <div className="flex items-center justify-between border border-border bg-secondary/20 px-3 py-3">
                            <span className="text-[12px] text-muted-foreground">待调度 / 待处理</span>
                            <span className="text-[18px] font-semibold text-foreground">
                              {resultLedger.queuedTaskCount + resultLedger.blockedTaskCount}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="flex min-h-0 flex-col border-l border-border bg-[#FBF9F3] px-5 py-6">
                    <div className="mb-4 border border-border bg-white px-4 py-4">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="size-4 text-primary" />
                        <h3 className="text-[16px] font-semibold text-foreground">主审最新播报</h3>
                      </div>
                      <p className="mt-3 text-[13px] leading-6 text-muted-foreground">
                        {chief.currentAction}
                      </p>
                    </div>

                    <div className="min-h-0 flex-1 overflow-hidden [&>div]:h-full">
                      <AuditEventList events={events} error={eventError} loading={eventLoading} />
                    </div>
                  </div>
                </div>
              </>
            )}
          </DialogPrimitive.Content>
        </DialogPortal>
      </Dialog>
    </>
  );
}
