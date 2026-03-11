import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ClipboardEvent } from 'react';
import { Flag, ImagePlus, LoaderCircle, MessageSquareMore, Send, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getFeedbackAttachmentUrl } from '@/api';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type { AuditResult } from '@/types';
import type { FeedbackThread } from '@/types/api';
import { getLearningDecisionLabel, getThreadStatusLabel } from './feedbackThreadPresentation';

type FeedbackThreadDrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  result: AuditResult | null;
  thread: FeedbackThread | null;
  loading: boolean;
  submitting: boolean;
  error: string;
  onSubmitMessage: (payload: { content: string; images: File[] }) => Promise<void> | void;
  onRevokeIncorrect?: () => Promise<void> | void;
};

type DraftImageItem = {
  file: File;
  previewUrl: string;
};

export default function FeedbackThreadDrawer({
  open,
  onOpenChange,
  result,
  thread,
  loading,
  submitting,
  error,
  onSubmitMessage,
  onRevokeIncorrect,
}: FeedbackThreadDrawerProps) {
  const [draft, setDraft] = useState('');
  const [draftImages, setDraftImages] = useState<DraftImageItem[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) {
      setDraft('');
      setDraftImages((current) => {
        current.forEach((item) => URL.revokeObjectURL(item.previewUrl));
        return [];
      });
    }
  }, [open]);

  const messages = useMemo(() => thread?.messages || [], [thread]);
  const reviewing = thread?.status === 'agent_reviewing';
  const unavailable = thread?.status === 'agent_unavailable';
  const draftImageLimitReached = draftImages.length >= 3;

  const appendDraftImages = (files: File[]) => {
    if (!files.length) return;
    setDraftImages((current) => {
      const remaining = Math.max(0, 3 - current.length);
      const nextItems = files
        .filter((file) => file.type.startsWith('image/'))
        .slice(0, remaining)
        .map((file) => ({
          file,
          previewUrl: URL.createObjectURL(file),
        }));
      return [...current, ...nextItems];
    });
  };

  const handleSend = async () => {
    const content = draft.trim();
    if (!content && draftImages.length === 0) return;
    await onSubmitMessage({ content, images: draftImages.map((item) => item.file) });
    setDraft('');
    setDraftImages((current) => {
      current.forEach((item) => URL.revokeObjectURL(item.previewUrl));
      return [];
    });
  };

  const handlePickImages = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    appendDraftImages(files);
    event.target.value = '';
  };

  const handlePaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(event.clipboardData.items || [])
      .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
      .map((item) => item.getAsFile())
      .filter((file): file is File => !!file);
    if (!files.length) return;
    event.preventDefault();
    appendDraftImages(files);
  };

  const removeDraftImage = (index: number) => {
    setDraftImages((current) => {
      const target = current[index];
      if (target) URL.revokeObjectURL(target.previewUrl);
      return current.filter((_, itemIndex) => itemIndex !== index);
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(92vw,960px)] max-w-[960px] rounded-none border border-border bg-white p-0 gap-0">
        <div className="grid min-h-[620px] grid-cols-1 lg:grid-cols-[300px_minmax(0,1fr)]">
          <aside className="border-b border-border bg-secondary/20 p-6 lg:border-b-0 lg:border-r">
            <DialogHeader className="text-left space-y-3">
              <div className="inline-flex h-10 w-10 items-center justify-center border border-border bg-white">
                <Flag className="h-5 w-5 text-destructive" />
              </div>
              <div className="space-y-2">
                <DialogTitle className="text-[22px] font-semibold text-foreground">反馈会话</DialogTitle>
                <DialogDescription className="text-[13px] leading-6 text-muted-foreground">
                  不再只是留一句备注。这里会把误报反馈交给 Agent 判断，并明确告诉你它会不会学习。
                </DialogDescription>
              </div>
            </DialogHeader>

            <div className="mt-6 space-y-4 text-[13px]">
              <section className="space-y-2">
                <p className="text-xs font-medium tracking-wide text-muted-foreground">问题上下文</p>
                <div className="border border-border bg-white p-3 space-y-2">
                  <p className="text-sm font-medium text-foreground">{result?.description || '当前问题还没有文字说明。'}</p>
                  <p className="text-muted-foreground">规则：{result?.rule_id || '未记录'}</p>
                  <p className="text-muted-foreground">来源：{result?.source_agent || '未记录'}</p>
                  <p className="text-muted-foreground">置信度：{result?.confidence != null ? result.confidence.toFixed(2) : '未记录'}</p>
                </div>
              </section>

              <section className="space-y-2">
                <p className="text-xs font-medium tracking-wide text-muted-foreground">当前判断</p>
                <div className="space-y-2">
                  <div className="border border-border bg-white px-3 py-2">
                    <p className="text-[11px] text-muted-foreground">误报判定</p>
                    <p className="mt-1 text-sm font-medium text-foreground">{getThreadStatusLabel(thread?.status)}</p>
                  </div>
                  <div className="border border-border bg-white px-3 py-2">
                    <p className="text-[11px] text-muted-foreground">学习处理</p>
                    <p className="mt-1 text-sm font-medium text-foreground">{getLearningDecisionLabel(thread?.learning_decision)}</p>
                  </div>
                </div>
              </section>

              {thread?.summary ? (
                <section className="space-y-2">
                  <p className="text-xs font-medium tracking-wide text-muted-foreground">Agent 摘要</p>
                  <div className="border border-border bg-white p-3 text-sm leading-6 text-foreground">
                    {thread.summary}
                  </div>
                </section>
              ) : null}
            </div>
          </aside>

          <section className="flex min-h-0 flex-col">
            <div className="border-b border-border px-6 py-4">
              <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
                <MessageSquareMore className="h-4 w-4" />
                <span>和误报反馈 Agent 对话</span>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5 space-y-3">
              {loading ? (
                <div className="border border-border bg-secondary/20 px-4 py-3 text-sm text-muted-foreground">
                  正在加载这条反馈会话...
                </div>
              ) : messages.length === 0 ? (
                <div className="border border-dashed border-border px-4 py-6 text-sm leading-6 text-muted-foreground">
                  先说说为什么你觉得这是误报，Agent 会马上给出第一轮判断。
                </div>
              ) : messages.map((message) => (
                <div
                  key={message.id}
                  className={message.role === 'user'
                    ? 'ml-auto max-w-[80%] border border-border bg-secondary/20 px-4 py-3'
                    : 'mr-auto max-w-[85%] border border-border bg-white px-4 py-3'}
                >
                  <p className="mb-1 text-[11px] font-medium text-muted-foreground">
                    {message.role === 'user' ? '你' : message.role === 'agent' ? 'Agent' : '系统'}
                  </p>
                  <p className="text-sm leading-6 text-foreground">{message.content}</p>
                  {message.attachments?.length ? (
                    <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {message.attachments.map((attachment) => (
                        <a
                          key={attachment.id}
                          href={getFeedbackAttachmentUrl(attachment.file_url)}
                          target="_blank"
                          rel="noreferrer"
                          className="block border border-border bg-background p-2"
                        >
                          <img
                            src={getFeedbackAttachmentUrl(attachment.file_url)}
                            alt={attachment.file_name}
                            className="h-28 w-full object-cover"
                          />
                          <p className="mt-2 truncate text-[11px] text-muted-foreground">{attachment.file_name}</p>
                        </a>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
              {reviewing ? (
                <div className="mr-auto max-w-[85%] border border-border bg-white px-4 py-3">
                  <p className="mb-1 text-[11px] font-medium text-muted-foreground">Agent</p>
                  <div className="flex items-center gap-2 text-sm leading-6 text-foreground">
                    <LoaderCircle className="h-4 w-4 animate-spin text-muted-foreground" />
                    <span>误报反馈Agent 正在思考...</span>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="border-t border-border px-6 py-4 space-y-3">
              {error ? (
                <div className="border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  {error}
                </div>
              ) : null}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={handlePickImages}
              />
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onPaste={handlePaste}
                placeholder="先说说为什么你觉得这是误报"
                rows={4}
                className="w-full resize-none rounded-none border border-border bg-white px-3 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>支持上传或直接粘贴图片，最多 3 张。</span>
                  <span>{draftImages.length}/3</span>
                </div>
                {draftImages.length ? (
                  <div className="grid grid-cols-3 gap-2">
                    {draftImages.map((item, index) => (
                      <div key={`${item.file.name}-${index}`} className="relative border border-border bg-white p-1">
                        <img src={item.previewUrl} alt={item.file.name} className="h-20 w-full object-cover" />
                        <button
                          type="button"
                          className="absolute right-1 top-1 inline-flex h-6 w-6 items-center justify-center border border-border bg-white"
                          onClick={() => removeDraftImage(index)}
                          aria-label={`移除图片 ${item.file.name}`}
                        >
                          <X className="h-3 w-3" />
                        </button>
                        <p className="mt-1 truncate text-[11px] text-muted-foreground">{item.file.name}</p>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  {reviewing
                    ? '误报反馈Agent 正在思考，你先等这一轮返回。'
                    : unavailable
                      ? '误报反馈Agent 当前未联通，你可以稍后重试。'
                      : draftImageLimitReached
                        ? '已经到 3 张上限了，删掉一张再补。'
                        : ''}
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    className="rounded-none"
                    disabled={submitting || loading || reviewing || draftImageLimitReached}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <ImagePlus className="h-4 w-4" />
                    上传图片
                  </Button>
                  {result?.feedback_status === 'incorrect' && onRevokeIncorrect ? (
                    <Button
                      type="button"
                      variant="outline"
                      className="rounded-none"
                      disabled={submitting || loading || reviewing}
                      onClick={() => void onRevokeIncorrect()}
                    >
                      撤销误报
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    className="rounded-none"
                    disabled={submitting || loading || reviewing || (!draft.trim() && draftImages.length === 0)}
                    onClick={() => void handleSend()}
                  >
                    <Send className="h-4 w-4" />
                    发送给 Agent
                  </Button>
                </div>
              </div>
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
