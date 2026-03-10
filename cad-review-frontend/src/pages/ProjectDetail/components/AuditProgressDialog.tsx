import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Check, Loader2, Minus, RefreshCw, TriangleAlert, X } from "lucide-react";
import { useMemo, useState } from "react";
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
import { cn } from "@/lib/utils";
import type { AuditEvent } from "@/types/api";
import type { AuditProviderMode } from "@/types/api";
import AuditEventList from "./AuditEventList";

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
  etaText: string;
  phases: AuditPhaseCard[];
  events: AuditEvent[];
  eventError?: string;
  eventLoading?: boolean;
  providerLabel?: string;
  onMinimize: () => void;
  onRequestClose: (onStep: (step: string) => void) => Promise<void>;
  closeDisabled?: boolean;
}

export function getAuditProviderLabel(value?: AuditProviderMode | string | null) {
  return value === "codex_sdk" ? "Codex SDK" : "Kimi SDK";
}

export function AuditProviderSelector({
  value,
  onChange,
  defaultLabel,
}: {
  value: AuditProviderMode;
  onChange: (next: AuditProviderMode) => void;
  defaultLabel?: string;
}) {
  return (
    <fieldset className="space-y-3">
      <legend className="text-[13px] font-semibold text-foreground">本轮审核引擎选择</legend>
      <p className="text-[12px] leading-5 text-muted-foreground">
        {defaultLabel ? `默认会先选 ${defaultLabel}，这次你也可以临时改。` : '这次审核想走哪条引擎路线，就在这里直接选。'}
      </p>
      <div className="grid grid-cols-1 gap-3">
        {([
          { value: "kimi_sdk", label: "Kimi SDK", description: "继续走现有 Kimi SDK 路线，更稳。", },
          { value: "codex_sdk", label: "Codex SDK", description: "改走新的 Codex SDK 路线，便于本轮验证。", },
        ] as const).map((option) => (
          <label
            key={option.value}
            className={cn(
              "flex cursor-pointer items-start gap-3 border px-4 py-3 transition-colors",
              value === option.value ? "border-primary bg-primary/5" : "border-border bg-white hover:border-primary/40",
            )}
          >
            <input
              type="radio"
              name="audit-provider-mode"
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="mt-1 h-4 w-4 accent-primary"
              aria-label={option.label}
            />
            <span className="space-y-1">
              <span className="block text-[14px] font-semibold text-foreground">{option.label}</span>
              <span className="block text-[12px] leading-5 text-muted-foreground">{option.description}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function AuditProgressPill({
  progress,
  onClick,
}: {
  progress: number;
  onClick: () => void;
}) {
  const label = progress >= 90 ? "快好了" : "审核中";

  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex h-8 items-center gap-2 border border-border bg-secondary px-3 text-[13px] font-medium text-foreground transition-colors hover:bg-secondary/80"
    >
      <RefreshCw className="h-3.5 w-3.5 animate-spin text-primary" />
      <span>{label}</span>
      <span className="text-muted-foreground">{Math.round(progress)}%</span>
    </button>
  );
}

export default function AuditProgressDialog({
  open,
  progress,
  headline,
  supportingText,
  etaText,
  phases,
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
  const latestEvent = useMemo(() => events[events.length - 1] ?? null, [events]);
  const activeAgentName = latestEvent?.agent_name || headline;
  const activeAgentMessage = latestEvent?.message || supportingText;

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
          className="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-48px)] max-w-[820px] -translate-x-1/2 -translate-y-1/2 border border-border bg-white p-0 outline-none"
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
              <div className="border-b border-border px-8 py-7">
                <div className="flex items-start justify-between gap-6">
                  <div className="space-y-3">
                    <DialogTitle className="text-[28px] font-semibold tracking-tight text-foreground">
                      AI 正在帮你审图
                    </DialogTitle>
                    <DialogDescription className="max-w-[560px] text-[14px] leading-6 text-muted-foreground">
                      系统已经开始按 Agent 分工持续审图。你不用一直守着页面，右侧日志会不断追加当前动作和阶段进展。
                    </DialogDescription>
                    <div className="flex flex-wrap items-center gap-3 text-[13px]">
                      <span className="rounded-full border border-border bg-secondary/40 px-3 py-1 font-medium text-foreground">
                        当前执行：{activeAgentName}
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

              <div className="px-8 py-8">
                <div className="border border-border bg-secondary/20 px-6 py-6">
                  <div className="flex items-center gap-3">
                    <RefreshCw className="h-5 w-5 animate-spin text-primary" />
                    <p className="text-[22px] font-semibold leading-8 text-foreground">{headline}</p>
                  </div>

                  <p className="mt-3 text-[14px] leading-6 text-muted-foreground">
                    {activeAgentMessage}
                  </p>

                  <div className="mt-6">
                    <Progress
                      value={progress}
                      className="h-2.5 rounded-none bg-secondary [&>div]:bg-primary"
                    />
                    <div className="mt-3 flex items-center justify-between text-[13px] text-muted-foreground">
                      <span>当前进度：{Math.round(progress)}%</span>
                      <span>{etaText}</span>
                    </div>
                  </div>
                </div>

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
                            phase.state === "complete" && "border-success bg-success text-white",
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
              </div>
            </>
          )}
        </DialogPrimitive.Content>
        {!shuttingDown ? (
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
