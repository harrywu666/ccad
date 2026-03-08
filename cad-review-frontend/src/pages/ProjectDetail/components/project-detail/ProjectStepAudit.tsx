import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, ChevronDown, Database, Download, Flag, History, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import * as api from '@/api';
import type { AuditFeedbackStatus, AuditIssuePreviewDrawingAsset, AuditResult, AuditStatus, Drawing } from '@/types';
import type { AuditHistoryItem } from '@/types/api';
import type { PreviewDrawing } from '../../hooks/useDrawingPreview';
import InlineDrawingPreviewPanel from './InlineDrawingPreviewPanel';

interface ProjectStepAuditProps {
  projectId?: string;
  projectStatus: string;
  projectCacheVersion?: number;
  auditStatus: AuditStatus | null;
  auditHistory: AuditHistoryItem[];
  selectedAuditVersion: number | null;
  auditResults: AuditResult[];
  drawings: Drawing[];
  stageTitle: string;
  onSelectAuditVersion: (version: number) => void;
  onRequestDeleteVersion: (version: number) => void;
  onAuditResultsChange: (results: AuditResult[]) => void;
  onInlinePreviewChange?: (open: boolean) => void;
}

const TYPE_LABEL_MAP: Record<string, string> = {
  index: '索引',
  dimension: '尺寸',
  material: '材料',
};

type SelectedPreview = {
  issueId: string;
  drawingA: PreviewDrawing | null;
  drawingB: PreviewDrawing | null;
  missingReason: string | null;
  description: string;
};

function getTypeLabel(type: string) {
  return TYPE_LABEL_MAP[type] || '其他问题';
}

function getLocationDisplay(result: AuditResult) {
  const locations = (result.locations || []).filter(Boolean);
  if (locations.length === 0) return result.location || null;
  if (locations.length <= 4) return locations.join('、');
  return `${locations.slice(0, 4).join('、')} 等${locations.length}处`;
}

function FeedbackPopover({
  result,
  isIncorrect,
  isPending,
  onSubmit,
  onRevoke,
}: {
  result: AuditResult;
  isIncorrect: boolean;
  isPending: boolean;
  onSubmit: (note?: string) => void;
  onRevoke: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleOpen = (nextOpen: boolean) => {
    if (isIncorrect) {
      if (!nextOpen) setOpen(false);
      return;
    }
    setOpen(nextOpen);
    if (nextOpen) {
      setNote('');
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  };

  const handleSubmit = () => {
    onSubmit(note.trim() || undefined);
    setOpen(false);
    setNote('');
  };

  if (isIncorrect) {
    return (
      <Popover open={open} onOpenChange={handleOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="rounded-none shadow-none bg-destructive/10 text-destructive hover:bg-destructive/15 hover:text-destructive"
            disabled={isPending}
            aria-label={`撤销误报反馈：${result.sheet_no_a || '未命名图纸'}`}
            title={result.feedback_note ? `已反馈误报：${result.feedback_note}` : '已反馈误报，点击可撤销'}
          >
            <Flag className="w-4 h-4" />
          </Button>
        </PopoverTrigger>
        <PopoverContent side="right" align="center" className="w-56 p-3 space-y-2">
          {result.feedback_note ? (
            <p className="text-xs text-muted-foreground leading-relaxed">{result.feedback_note}</p>
          ) : (
            <p className="text-xs text-muted-foreground">已标记为误报</p>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full text-xs"
            disabled={isPending}
            onClick={() => {
              onRevoke();
              setOpen(false);
            }}
          >
            撤销反馈
          </Button>
        </PopoverContent>
      </Popover>
    );
  }

  return (
    <Popover open={open} onOpenChange={handleOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="rounded-none shadow-none text-muted-foreground hover:bg-secondary hover:text-foreground"
          disabled={isPending}
          aria-label={`提交误报反馈：${result.sheet_no_a || '未命名图纸'}`}
          title="反馈为误报"
        >
          <Flag className="w-4 h-4" />
        </Button>
      </PopoverTrigger>
        <PopoverContent side="right" align="center" className="w-64 p-3 space-y-2">
        <p className="text-xs font-medium text-foreground">反馈为误报</p>
        <textarea
          ref={inputRef}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="可选：简述误报原因"
          rows={2}
          className="w-full resize-none rounded border border-input bg-background px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              handleSubmit();
            }
          }}
        />
        <div className="flex gap-1.5">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="flex-1 text-xs"
            onClick={() => setOpen(false)}
          >
            取消
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            className="flex-1 text-xs"
            disabled={isPending}
            onClick={handleSubmit}
          >
            确认误报
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export default function ProjectStepAudit({
  projectId,
  projectStatus,
  projectCacheVersion,
  auditStatus,
  auditHistory,
  selectedAuditVersion,
  auditResults,
  drawings: _drawings,
  stageTitle,
  onSelectAuditVersion,
  onRequestDeleteVersion,
  onAuditResultsChange,
  onInlinePreviewChange,
}: ProjectStepAuditProps) {
  const [pendingIds, setPendingIds] = useState<Record<string, boolean>>({});
  const [actionError, setActionError] = useState('');
  const [selectedPreview, setSelectedPreview] = useState<SelectedPreview | null>(null);
  const [previewView, setPreviewView] = useState<'a' | 'b'>('a');
  const previewRequestRef = useRef(0);

  useEffect(() => {
    if (!selectedPreview) return;
    const exists = auditResults.some((item) => item.id === selectedPreview.issueId);
    if (!exists) {
      setSelectedPreview(null);
      setPreviewView('a');
    }
  }, [auditResults, selectedPreview]);

  useEffect(() => {
    onInlinePreviewChange?.(Boolean(selectedPreview));
  }, [onInlinePreviewChange, selectedPreview]);

  const unresolvedCounts = useMemo(() => ({
    index: auditResults.filter((result) => result.type === 'index' && !result.is_resolved).length,
    dimension: auditResults.filter((result) => result.type === 'dimension' && !result.is_resolved).length,
    material: auditResults.filter((result) => result.type === 'material' && !result.is_resolved).length,
  }), [auditResults]);

  const totalCount = auditResults.length;

  const reportDownloadUrl = projectId
    ? api.downloadPdfReport(projectId, selectedAuditVersion || auditStatus?.audit_version || undefined)
    : '#';

  const selectedVersionMeta = selectedAuditVersion !== null
    ? auditHistory.find((item) => item.version === selectedAuditVersion) || null
    : null;
  const selectedVersionDisplayCount = selectedVersionMeta?.grouped_count ?? selectedVersionMeta?.count ?? totalCount;

  const formatVersionTime = (value?: string | null) => {
    if (!value) return '无时间';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '无时间';
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const resolvePreviewDrawing = (asset: AuditIssuePreviewDrawingAsset | null): PreviewDrawing | null => {
    if (!projectId || !asset?.drawing_id) return null;
    return {
      drawingId: asset.drawing_id,
      dataVersion: asset.drawing_data_version ?? 1,
      sheetNo: asset.sheet_no || '未命名图号',
      sheetName: asset.sheet_name || '未命名图纸',
      pageIndex: asset.page_index ?? null,
      imageUrl: api.getDrawingImageUrl(projectId, asset.drawing_id, projectCacheVersion),
      focusAnchor: asset.pdf_anchor || asset.anchor || asset.layout_anchor || null,
      focusHighlightRegion: asset.highlight_region || asset.pdf_anchor?.highlight_region || asset.anchor?.highlight_region || asset.layout_anchor?.highlight_region || null,
      focusAnchorStatus: asset.anchor_status || null,
      focusRegistrationConfidence: asset.registration_confidence ?? null,
    };
  };

  const openIssueDrawing = async (result: AuditResult) => {
    if (!projectId) return;
    const requestId = previewRequestRef.current + 1;
    previewRequestRef.current = requestId;
    setActionError('');

    try {
      const previewId = result.issue_ids && result.issue_ids.length > 0 ? result.issue_ids[0] : result.id;
      const preview = await api.getAuditResultPreview(projectId, previewId);
      if (previewRequestRef.current !== requestId) return;

      setPreviewView('a');
      setSelectedPreview({
        issueId: result.id,
        drawingA: resolvePreviewDrawing(preview.source),
        drawingB: resolvePreviewDrawing(preview.target),
        missingReason: preview.missing_reason,
        description:
          preview.missing_reason === 'missing_target_drawing'
            ? '目标图不存在，已自动定位到源图中的出错索引。'
            : (preview.issue.description || result.description || ''),
      });
    } catch (error) {
      console.error('加载问题图纸预览失败', error);
      if (previewRequestRef.current !== requestId) return;
      setActionError('这条问题的精确图纸定位加载失败了，请稍后再试。');
    }
  };

  const handleToggleResolved = async (result: AuditResult, nextResolved: boolean) => {
    if (!projectId) return;
    const previous = auditResults;
    setActionError('');
    setPendingIds((current) => ({ ...current, [result.id]: true }));
    const targetIssueIds = result.issue_ids && result.issue_ids.length > 0 ? result.issue_ids : [result.id];

    const optimistic = auditResults.map((item) => (
      item.id === result.id
        ? {
            ...item,
            is_resolved: nextResolved,
            resolved_at: nextResolved ? new Date().toISOString() : null,
          }
        : item
    ));
    onAuditResultsChange(optimistic);

    try {
      if (targetIssueIds.length > 1 || result.is_grouped) {
        await api.batchUpdateAuditResults(projectId, targetIssueIds, { is_resolved: nextResolved });
        onAuditResultsChange(optimistic);
      } else {
        const updated = await api.updateAuditResult(projectId, result.id, { is_resolved: nextResolved });
        onAuditResultsChange(optimistic.map((item) => (item.id === updated.id ? updated : item)));
      }
    } catch (error) {
      console.error('更新问题处理状态失败', error);
      onAuditResultsChange(previous);
      setActionError('保存失败，这条问题的处理状态没有改成功。');
    } finally {
      setPendingIds((current) => {
        const next = { ...current };
        delete next[result.id];
        return next;
      });
    }
  };

  const handleToggleFeedback = async (
    result: AuditResult,
    nextStatus: AuditFeedbackStatus,
    note?: string,
  ) => {
    if (!projectId) return;
    const previous = auditResults;
    setActionError('');
    setPendingIds((current) => ({ ...current, [result.id]: true }));
    const targetIssueIds = result.issue_ids && result.issue_ids.length > 0 ? result.issue_ids : [result.id];
    const nextFeedbackAt = nextStatus === 'incorrect' ? new Date().toISOString() : null;
    const nextNote = nextStatus === 'incorrect' ? (note ?? null) : null;

    const optimistic = auditResults.map((item) => (
      item.id === result.id
        ? {
            ...item,
            feedback_status: nextStatus,
            feedback_at: nextFeedbackAt,
            feedback_note: nextNote,
          }
        : item
    ));
    onAuditResultsChange(optimistic);

    const payload: api.AuditResultUpdatePayload = { feedback_status: nextStatus };
    if (nextStatus === 'incorrect' && note) {
      payload.feedback_note = note;
    }

    try {
      if (targetIssueIds.length > 1 || result.is_grouped) {
        await api.batchUpdateAuditResults(projectId, targetIssueIds, payload);
        onAuditResultsChange(optimistic);
      } else {
        const updated = await api.updateAuditResult(projectId, result.id, payload);
        onAuditResultsChange(optimistic.map((item) => (item.id === updated.id ? updated : item)));
      }
    } catch (error) {
      console.error('更新误报反馈状态失败', error);
      onAuditResultsChange(previous);
      setActionError('保存失败，这条问题的误报反馈没有改成功。');
    } finally {
      setPendingIds((current) => {
        const next = { ...current };
        delete next[result.id];
        return next;
      });
    }
  };

  const selectedIssue = selectedPreview
    ? auditResults.find((item) => item.id === selectedPreview.issueId) || null
    : null;

  if (projectStatus === 'auditing') {
    return null;
  }

  return (
    <div className="w-full space-y-8 animate-in fade-in duration-500">
      <div className="space-y-6">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h2 className="text-[24px] font-semibold flex items-center gap-2">
              <CheckCircle2 className="h-6 w-6 text-success" />
              审核报告就绪
            </h2>
            <p className="text-[14px] text-muted-foreground mt-1 text-balance">
              全部深度核查完成。左边可以逐条处理问题，右边可以直接看对应图纸。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  className="rounded-none bg-white shadow-none h-10 px-4 min-w-[240px] justify-between"
                >
                  <span className="flex items-center gap-2">
                    <History className="w-4 h-4" />
                    {selectedAuditVersion !== null ? `审核版本 · v${selectedAuditVersion}` : '审核版本'}
                  </span>
                  <ChevronDown className="w-4 h-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-[420px] rounded-none p-0">
                <div className="border-b border-border px-4 py-3 text-[12px] text-muted-foreground">
                  选择一个审核版本查看，或直接删除不需要的旧版本。
                </div>
                {auditHistory.length === 0 ? (
                  <div className="px-4 py-6 text-[13px] text-muted-foreground">当前还没有审核版本。</div>
                ) : auditHistory.map((item) => {
                  const isSelected = item.version === selectedAuditVersion;
                  const canDelete = item.status !== 'running';
                  return (
                    <div
                      key={item.version}
                      className={`flex items-center gap-3 border-t border-border px-4 py-3 ${isSelected ? 'bg-secondary' : 'bg-white hover:bg-secondary/50'}`}
                    >
                      <button
                        type="button"
                        className="flex-1 text-left"
                        onClick={() => onSelectAuditVersion(item.version)}
                      >
                        <div className="flex items-center justify-between gap-4">
                          <div className="text-[14px] font-medium text-foreground">v{item.version}</div>
                          <div className="text-[12px] text-muted-foreground">{formatVersionTime(item.finished_at || item.started_at)}</div>
                        </div>
                        <div className="mt-1 flex items-center gap-3 text-[12px] text-muted-foreground">
                          <span>{item.grouped_count ?? item.count}条问题</span>
                          <span>{item.status === 'done' ? '已完成' : item.status === 'failed' ? '失败' : item.status}</span>
                        </div>
                      </button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="rounded-none h-9 w-9 shrink-0"
                        disabled={!canDelete}
                        onClick={(event) => {
                          event.stopPropagation();
                          onRequestDeleteVersion(item.version);
                        }}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              asChild
              className="rounded-none bg-primary shadow-none h-10 w-[160px]"
            >
              <a href={reportDownloadUrl} target="_blank" rel="noreferrer">
                <Download className="w-4 h-4 mr-2" />
                导出详细报告
              </a>
            </Button>
          </div>
        </div>

        {actionError ? (
          <div className="border border-destructive/30 bg-destructive/5 px-4 py-3 text-[13px] text-destructive">
            {actionError}
          </div>
        ) : null}

        {selectedVersionMeta ? (
          <div className="border border-border bg-secondary/20 px-4 py-3 text-[13px] text-muted-foreground">
            当前查看 <span className="font-medium text-foreground">v{selectedVersionMeta.version}</span>
            <span className="mx-2">·</span>
            {selectedVersionDisplayCount}条问题
            <span className="mx-2">·</span>
            {formatVersionTime(selectedVersionMeta.finished_at || selectedVersionMeta.started_at)}
          </div>
        ) : null}

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
          <Card className="rounded-none border-border shadow-none bg-secondary/10">
            <CardContent className="p-6">
              <p className="text-[13px] text-muted-foreground mb-2">问题总数</p>
              <p className="text-[32px] font-semibold text-foreground leading-none">{totalCount}</p>
            </CardContent>
          </Card>
          <Card className="rounded-none border-border shadow-none bg-destructive/5">
            <CardContent className="p-6">
              <p className="text-[13px] text-destructive/80 mb-2 flex items-center gap-1.5">
                <AlertCircle className="w-4 h-4" />
                未解决索引问题
              </p>
              <p className="text-[32px] font-semibold text-destructive leading-none">{unresolvedCounts.index}</p>
            </CardContent>
          </Card>
          <Card className="rounded-none border-border shadow-none bg-destructive/5">
            <CardContent className="p-6">
              <p className="text-[13px] text-destructive/80 mb-2 flex items-center gap-1.5">
                <AlertCircle className="w-4 h-4" />
                未解决尺寸问题
              </p>
              <p className="text-[32px] font-semibold text-destructive leading-none">{unresolvedCounts.dimension}</p>
            </CardContent>
          </Card>
          <Card className="rounded-none border-border shadow-none bg-destructive/5">
            <CardContent className="p-6">
              <p className="text-[13px] text-destructive/80 mb-2 flex items-center gap-1.5">
                <Database className="w-4 h-4" />
                未解决材料问题
              </p>
              <p className="text-[32px] font-semibold text-destructive leading-none">{unresolvedCounts.material}</p>
            </CardContent>
          </Card>
        </div>

        <div className={`${selectedPreview ? 'grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(680px,52vw)] xl:items-start gap-6' : 'block'}`}>
          <section className="min-w-0 space-y-4">
            <div className="border border-border bg-white overflow-hidden">
              <table className="w-full border-collapse">
                <thead className="bg-secondary/40 border-b border-border">
                  <tr>
                    <th className="w-[56px] px-2 py-3 text-center text-[12px] font-semibold text-foreground">处理</th>
                    <th className="w-[70px] pl-0 pr-2 py-3 text-center text-[12px] font-semibold text-foreground">问题类型</th>
                    <th className="w-[112px] px-2 py-3 text-left text-[12px] font-semibold text-foreground">关联图纸</th>
                    <th className="px-3 py-3 text-left text-[12px] font-semibold text-foreground">问题说明</th>
                    <th className="w-[72px] px-2 py-3 text-center text-[12px] font-semibold text-foreground whitespace-nowrap">误报</th>
                  </tr>
                </thead>
                <tbody>
                  {auditResults.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-12 text-center text-[14px] text-muted-foreground">
                        当前这一轮还没有发现问题。
                      </td>
                    </tr>
                  ) : auditResults.map((result) => {
                    const isResolved = Boolean(result.is_resolved);
                    const isPending = Boolean(pendingIds[result.id]);
                    const isActive = selectedPreview?.issueId === result.id;
                    const isIncorrectFeedback = result.feedback_status === 'incorrect';

                    return (
                      <tr
                        key={result.id}
                        className={`border-t border-border align-top ${
                          isResolved
                            ? isActive ? 'bg-success/14' : 'bg-success/8 hover:bg-success/14'
                            : isActive ? 'bg-destructive/10' : 'bg-destructive/5 hover:bg-destructive/10'
                        } cursor-pointer transition-colors`}
                        onClick={() => { void openIssueDrawing(result); }}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            void openIssueDrawing(result);
                          }
                        }}
                        tabIndex={0}
                        aria-label={`查看${getTypeLabel(result.type)}：${result.sheet_no_a || '未命名图纸'}`}
                      >
                        <td className="px-2 py-4 text-center" onClick={(event) => event.stopPropagation()}>
                          <label className="inline-flex items-center justify-center text-[12px] text-muted-foreground">
                            <input
                              type="checkbox"
                              className="h-4 w-4 rounded-none border-border accent-[#0f9d58]"
                              checked={isResolved}
                              disabled={isPending}
                              onChange={(event) => {
                                void handleToggleResolved(result, event.target.checked);
                              }}
                            />
                          </label>
                        </td>
                        <td className="pl-0 pr-2 py-4 text-center">
                          <div className={`inline-flex min-h-7 items-center justify-center border px-2.5 text-[11px] font-semibold ${
                            isResolved
                              ? 'border-success/40 bg-success/10 text-success'
                              : 'border-destructive/20 bg-destructive text-white'
                          }`}>
                            {getTypeLabel(result.type)}
                          </div>
                        </td>
                        <td className="px-2 py-4 text-[12px] text-foreground">
                          <div className="space-y-1.5 leading-5">
                            <div className="font-medium">
                              <span className="text-muted-foreground">A:</span> {result.sheet_no_a || '-'}
                            </div>
                            <div className="font-medium">
                              <span className="text-muted-foreground">B:</span> {result.sheet_no_b || '-'}
                            </div>
                          </div>
                        </td>
                        <td className="px-3 py-4">
                          <div className="space-y-2">
                            {getLocationDisplay(result) ? (
                              <div className={`text-[12px] ${isActive ? 'font-semibold text-foreground' : 'font-medium text-foreground'}`}>
                                {getLocationDisplay(result)}
                              </div>
                            ) : null}
                            <div
                              className={`leading-6 transition-colors ${
                                isActive
                                  ? 'bg-white/85 border-l-2 border-primary px-2 py-1 text-[14px] font-medium text-foreground'
                                  : 'text-[13px] text-muted-foreground'
                              }`}
                            >
                              {result.description || '这条问题目前还没有补充文字说明。'}
                            </div>
                          </div>
                        </td>
                        <td className="px-2 py-4 text-center" onClick={(event) => event.stopPropagation()}>
                          <FeedbackPopover
                            result={result}
                            isIncorrect={isIncorrectFeedback}
                            isPending={isPending}
                            onSubmit={(note) => void handleToggleFeedback(result, 'incorrect', note)}
                            onRevoke={() => void handleToggleFeedback(result, 'none')}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {selectedPreview ? (
            <InlineDrawingPreviewPanel
              projectId={projectId || ''}
              auditVersion={selectedAuditVersion ?? 1}
              availableVersions={auditHistory.map((h) => h.version)}
              previewSessionKey={selectedPreview.issueId}
              title={selectedIssue ? `${getTypeLabel(selectedIssue.type)} · ${selectedIssue.sheet_no_a || '未命名图号'}` : '关联图纸'}
              description={selectedPreview.description}
              missingReason={selectedPreview.missingReason}
              drawingA={selectedPreview.drawingA}
              drawingB={selectedPreview.drawingB}
              activeView={previewView}
              onViewChange={setPreviewView}
              onClose={() => setSelectedPreview(null)}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
