import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Check, Loader2, Minus, RefreshCw, TriangleAlert, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogDescription, DialogOverlay, DialogPortal, DialogTitle } from "@/components/ui/dialog";
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
import { Progress } from "@/components/ui/progress";
import type { AuditEvent } from "@/types/api";
import AuditEventList from "./AuditEventList";
import PipelineVisualization from "./PipelineVisualization";
import type { AuditPipelineItem } from "./useAuditProgressViewModel";

type AuditPhaseState = "complete" | "current" | "pending";

interface AuditPhaseCard {
  title: string;
  description: string;
  state: AuditPhaseState;
}

interface AuditProgressDialogProps {
  open: boolean;
  progress: number;
  headline: string;
  supportingText: string;
  startedAt?: string | null;
  phases: AuditPhaseCard[];
  pipeline?: AuditPipelineItem[];
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
      <div className="min-w-0 truncate">审图中</div>
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
  phases,
  pipeline = [],
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
  const activeEvent = latestRunnerBroadcast ?? latestEvent;
  const activeAgentNameText = activeAgentName || activeEvent?.agent_name || headline;
  const activeAgentMessageText = activeAgentMessage || activeEvent?.message || supportingText;
  const elapsedText = useMemo(() => formatAuditElapsedText(startedAt, new Date(now)), [startedAt, now]);

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
        <DialogOverlay className="bg-black/30" />
        <DialogPrimitive.Content
          onEscapeKeyDown={(event) => event.preventDefault()}
          onInteractOutside={(event) => event.preventDefault()}
          className="fixed left-1/2 top-1/2 z-50 max-h-[calc(100vh-16px)] w-[calc(100vw-40px)] max-w-[1120px] -translate-x-1/2 -translate-y-1/2 overflow-hidden border border-border bg-white p-0 outline-none"
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
              <div className="border-b border-border px-8 py-5">
                <div className="flex items-start justify-between gap-6">
                  <div className="space-y-3">
                    <DialogTitle className="text-[24px] font-semibold tracking-tight text-foreground">
                      AI 正在帮你审图
                    </DialogTitle>
                    <DialogDescription className="max-w-[560px] text-[13px] leading-6 text-muted-foreground">
                      系统已经开始按阶段持续审图。你不用一直盯着页面，关键进展会用更容易理解的方式展示出来。
                    </DialogDescription>
                    <div className="flex flex-wrap items-center gap-3 text-[13px]">
                      <span className="rounded-full border border-border bg-secondary/40 px-3 py-1 font-medium text-foreground">
                        当前执行：{activeAgentNameText}
                      </span>
                      {providerLabel ? (
                        <span className="rounded-full border border-border bg-white px-3 py-1 font-medium text-foreground">
                          本轮引擎：{providerLabel}
                        </span>
                      ) : null}
                      {latestEvent?.event_kind === "heartbeat" ? (
                        <span className="text-muted-foreground">当前任务仍在持续处理中</span>
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

              <div className="grid min-h-0 max-h-[calc(100vh-128px)] gap-0 xl:grid-cols-[minmax(0,1fr)_380px]">
                <div className="min-h-0 overflow-y-auto px-8 py-5">
                  <div className="border border-border bg-secondary/20 px-5 py-5">
                    <div className="flex flex-wrap items-center gap-3">
                      <RefreshCw className="h-4 w-4 animate-spin text-primary" />
                      <p className="text-[20px] font-semibold leading-7 text-foreground">{headline}</p>
                      <Badge variant="outline" className="rounded-none px-2 py-1 text-[11px] font-medium">
                        已发现问题 {totalIssues}
                      </Badge>
                    </div>

                    <p className="mt-3 text-[13px] leading-6 text-muted-foreground">
                      {activeAgentMessageText}
                    </p>

                    <div className="mt-5">
                      <Progress
                        value={progress}
                        className="h-2.5 rounded-none bg-secondary [&>div]:bg-primary"
                      />
                      <div className="mt-2 flex items-center justify-between text-[12px] text-muted-foreground">
                        <span>当前进度：{Math.round(progress)}%</span>
                        <span>{elapsedText}</span>
                      </div>
                    </div>
                  </div>

                  {pipeline.length ? (
                    <div className="mt-4 border border-border bg-white px-5 py-5">
                      <div className="mb-3 flex items-center justify-between gap-3">
                        <div
                          className="space-y-1"
                        >
                          <h3 className="text-[16px] font-semibold text-foreground">审图流水线</h3>
                          <p className="text-[12px] leading-5 text-muted-foreground">
                            7 个阶段按真实进度依次推进，当前焦点会跟着最新播报切换。
                          </p>
                        </div>
                        <span className="text-[12px] text-muted-foreground">当前 Agent：{activeAgentNameText}</span>
                      </div>
                      <PipelineVisualization items={pipeline} />
                    </div>
                  ) : null}

                  {!pipeline.length ? (
                    <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
                    {phases.map((phase) => (
                      <div
                        key={phase.title}
                        className={cn(
                          "border px-5 py-5 text-left transition-colors",
                          phase.state === "current" && "border-primary bg-primary/5",
                          phase.state === "complete" && "border-border bg-secondary/20",
                          phase.state === "pending" && "border-border bg-white",
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <div
                            className={cn(
                              "flex h-6 w-6 items-center justify-center border text-[12px] font-medium",
                              phase.state === "current" && "border-primary bg-primary text-white",
                              phase.state === "complete" && "border-emerald-600 bg-emerald-600 text-white",
                              phase.state === "pending" && "border-border bg-secondary text-muted-foreground",
                            )}
                          >
                            {phase.state === "complete" ? <Check className="h-3.5 w-3.5" /> : null}
                            {phase.state === "current" ? <span>•</span> : null}
                            {phase.state === "pending" ? <span>·</span> : null}
                          </div>
                          <h4
                            className={cn(
                              "text-[16px] font-semibold",
                              phase.state === "pending" ? "text-muted-foreground" : "text-foreground",
                            )}
                          >
                            {phase.title}
                          </h4>
                        </div>
                        <p className="mt-3 text-[13px] leading-6 text-muted-foreground">
                          {phase.description}
                        </p>
                      </div>
                    ))}
                    </div>
                  ) : null}
                </div>

                {!shuttingDown ? (
                  <div className="flex min-h-0 flex-col border-l border-border bg-secondary/10 px-5 py-5">
                    <div className="min-h-0 flex-1 overflow-hidden [&>div]:h-full">
                      <AuditEventList events={events} error={eventError} loading={eventLoading} />
                    </div>
                  </div>
                ) : null}
              </div>
            </>
          )}
        </DialogPrimitive.Content>
        {!shuttingDown && !pipeline.length ? (
          <div className="pointer-events-none fixed bottom-6 right-6 top-6 z-50 hidden xl:block">
            <div className="pointer-events-auto h-full w-[380px] overflow-hidden">
              <AuditEventList events={events} error={eventError} loading={eventLoading} />
            </div>
          </div>
        ) : null}
      </DialogPortal>
    </Dialog>
    </>
  );
}
