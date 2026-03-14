import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, ChevronDown, Database, Download, Flag, History, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import * as api from '@/api';
import type { AuditFeedbackStatus, AuditIssuePreviewDrawingAsset, AuditResult, AuditStatus, Drawing } from '@/types';
import type { AuditHistoryItem, FeedbackThread, FeedbackThreadMessage } from '@/types/api';
import type { PreviewDrawing } from '../../hooks/useDrawingPreview';
import FeedbackThreadDrawer from './FeedbackThreadDrawer';
import { createFeedbackThreadStreamController } from '../feedbackThreadStream';
import { getLearningDecisionLabel, getThreadStatusLabel } from './feedbackThreadPresentation';
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
  reference_broken: '索引',
  annotation_missing: '尺寸',
};

type SelectedPreview = {
  issueId: string;
  drawingA: PreviewDrawing | null;
  drawingB: PreviewDrawing | null;
  missingReason: string | null;
  description: string;
  extraSourceAnchors?: any[];
  extraTargetAnchors?: any[];
};

function getTypeLabel(type: string) {
  const normalized = normalizeIssueType(type);
  if (normalized === 'index') return '索引';
  if (normalized === 'dimension') return '尺寸';
  if (normalized === 'material') return '材料';
  return TYPE_LABEL_MAP[type] || '其他问题';
}

export function normalizeIssueType(type: string | null | undefined): 'index' | 'dimension' | 'material' | 'other' {
  const raw = String(type || '').trim().toLowerCase();
  if (!raw) return 'other';
  if (raw === 'index' || raw.includes('reference') || raw.includes('callout')) return 'index';
  if (raw === 'dimension' || raw.includes('dimension') || raw.includes('annotation')) return 'dimension';
  if (raw === 'material' || raw.includes('material') || raw.includes('finish')) return 'material';
  return 'other';
}

export function parseLocationText(value: string | null | undefined): string | null {
  const text = String(value || '').trim();
  if (!text) return null;
  if (!text.startsWith('{')) return text;
  try {
    const obj = JSON.parse(text) as Record<string, unknown>;
    const sheetNo = String(obj.sheet_no || '').trim();
    const logicalTitle = String(obj.logical_sheet_title || '').trim();
    if (sheetNo && logicalTitle && logicalTitle !== sheetNo) return `${sheetNo} / ${logicalTitle}`;
    if (sheetNo) return sheetNo;
    if (logicalTitle) return logicalTitle;
    const center = Array.isArray(obj.center_canonical) ? obj.center_canonical : null;
    if (center && center.length >= 2) return '图纸坐标附近';
  } catch {
    return text;
  }
  return text;
}

function getLocationDisplay(result: AuditResult) {
  const locations = (result.locations || [])
    .map((item) => parseLocationText(item))
    .filter(Boolean) as string[];
  if (locations.length === 0) return parseLocationText(result.location);
  if (locations.length <= 4) return locations.join('、');
  return `${locations.slice(0, 4).join('、')} 等${locations.length}处`;
}

type AuditReportPresentation = {
  tone: 'success' | 'warning' | 'error';
  title: string;
  description: string;
};

export function isAuditReportRunning(projectStatus: string, auditStatus: AuditStatus | null): boolean {
  const project = String(projectStatus || '').toLowerCase();
  const status = String(auditStatus?.status || '').toLowerCase();
  const runStatus = String(auditStatus?.run_status || '').toLowerCase();
  return (
    project === 'auditing'
    || status === 'auditing'
    || ['planning', 'running', 'queued', 'pending'].includes(runStatus)
  );
}

export function buildIssuePreviewSignature(result: AuditResult | null): string {
  if (!result) return '';
  return JSON.stringify({
    id: result.id,
    description: result.description || '',
    location: result.location || '',
    finding_status: result.finding_status || '',
    review_round: result.review_round || 0,
    confidence: result.confidence || 0,
    evidence_json: result.evidence_json || '',
    issue_ids: result.issue_ids || [],
  });
}

export function resolveAuditReportPresentation(
  auditStatus: AuditStatus | null,
  selectedVersionMeta: AuditHistoryItem | null,
): AuditReportPresentation {
  const versionStatus = String(selectedVersionMeta?.status || '').trim().toLowerCase();
  const runStatus = String(auditStatus?.run_status || '').trim().toLowerCase();
  const status = String(auditStatus?.status || '').trim().toLowerCase();
  const running = (
    versionStatus === 'running'
    || status === 'auditing'
    || ['planning', 'running', 'queued', 'pending'].includes(runStatus)
  );
  const failed = versionStatus === 'failed' || runStatus === 'failed' || status === 'failed';

  if (running) {
    return {
      tone: 'warning',
      title: '审图进行中',
      description: '审图还在持续处理中，问题会陆续追加到下方列表。你可以先处理已经出现的问题。',
    };
  }

  if (failed) {
    return {
      tone: 'error',
      title: '审核已中断',
      description: '这轮审图没有正常跑完，当前展示的是中断前已经写入的问题，不是完整报告。开发层运行细节可以去设置页里的运行总结查看。',
    };
  }

  if (auditStatus?.scope_mode === 'partial') {
    try {
      const scope = JSON.parse(auditStatus?.scope_summary || '{}');
      return {
        tone: 'warning',
        title: '审核报告就绪（部分覆盖）',
        description: `已对 ${scope.ready ?? '?'} / ${scope.total ?? '?'} 张就绪图纸完成深度核查，缺项图纸已跳过。左边可以逐条处理问题，右边可以直接看对应图纸。`,
      };
    } catch {
      return {
        tone: 'warning',
        title: '审核报告就绪（部分覆盖）',
        description: '部分图纸因缺项跳过，仅对就绪图纸完成深度核查。左边可以逐条处理问题，右边可以直接看对应图纸。',
      };
    }
  }

  return {
    tone: 'success',
    title: '审核报告就绪',
    description: '全部深度核查完成。左边可以逐条处理问题，右边可以直接看对应图纸。',
  };
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
  const [feedbackDrawerOpen, setFeedbackDrawerOpen] = useState(false);
  const [activeFeedbackResultId, setActiveFeedbackResultId] = useState<string | null>(null);
  const [activeFeedbackThread, setActiveFeedbackThread] = useState<FeedbackThread | null>(null);
  const [feedbackThreadsByResultId, setFeedbackThreadsByResultId] = useState<Record<string, FeedbackThread>>({});
  const [feedbackThreadLoading, setFeedbackThreadLoading] = useState(false);
  const [feedbackThreadSubmitting, setFeedbackThreadSubmitting] = useState(false);
  const [feedbackThreadError, setFeedbackThreadError] = useState('');
  const previewRequestRef = useRef(0);
  const selectedIssueSignatureRef = useRef('');
  const auditResultsRef = useRef(auditResults);
  const activeFeedbackThreadIdRef = useRef<string | null>(null);
  const activeFeedbackResultIdRef = useRef<string | null>(null);

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

  useEffect(() => {
    auditResultsRef.current = auditResults;
  }, [auditResults]);

  useEffect(() => {
    activeFeedbackThreadIdRef.current = activeFeedbackThread?.id || null;
  }, [activeFeedbackThread]);

  useEffect(() => {
    activeFeedbackResultIdRef.current = activeFeedbackResultId;
  }, [activeFeedbackResultId]);

  const refreshFeedbackThreadSummaries = async (currentResults: AuditResult[]) => {
    if (!projectId || currentResults.length === 0) {
      setFeedbackThreadsByResultId({});
      return;
    }

    const rowIdsByTargetId = new Map<string, string[]>();
    currentResults.forEach((result) => {
      const targetId = result.id;
      const rowIds = rowIdsByTargetId.get(targetId) || [];
      rowIds.push(result.id);
      rowIdsByTargetId.set(targetId, rowIds);
    });
    const targetIds = Array.from(rowIdsByTargetId.keys());
    if (targetIds.length === 0) {
      setFeedbackThreadsByResultId({});
      return;
    }

    try {
      const threads = await api.listFeedbackThreadsByResults(projectId, targetIds, {
        auditVersion: selectedAuditVersion ?? auditStatus?.audit_version ?? undefined,
      });
      const nextMap: Record<string, FeedbackThread> = {};
      threads.forEach((thread) => {
        const threadRefId = thread.result_group_id || thread.audit_result_id;
        const rowIds = rowIdsByTargetId.get(threadRefId) || [];
        rowIds.forEach((rowId) => {
          nextMap[rowId] = thread;
        });
      });
      setFeedbackThreadsByResultId(nextMap);
    } catch (error) {
      console.error('批量加载误报反馈线程失败', error);
    }
  };

  const applyFeedbackThreadUpdate = (
    thread: FeedbackThread,
    options?: { fallbackNote?: string | null; sourceResultId?: string | null; updateActiveThread?: boolean; allowActivateDrawerThread?: boolean },
  ) => {
    const currentResults = auditResultsRef.current;
    const matchedRows = currentResults.filter((item) => {
      if (thread.result_group_id) {
        return item.id === thread.result_group_id || item.group_id === thread.result_group_id;
      }
      return item.id === thread.audit_result_id || (item.issue_ids || []).includes(thread.audit_result_id);
    });
    const sourceResultId = options?.sourceResultId || null;
    const fallbackNote = options?.fallbackNote ?? null;
    const targetRows = matchedRows.length > 0
      ? matchedRows
      : (sourceResultId ? currentResults.filter((item) => item.id === sourceResultId) : []);

    const shouldUpdateActiveThread = options?.updateActiveThread ?? true;
    const allowActivateDrawerThread = options?.allowActivateDrawerThread ?? false;

    if (targetRows.length === 0) {
      if (shouldUpdateActiveThread && activeFeedbackThreadIdRef.current === thread.id) {
        setActiveFeedbackThread(thread);
      }
      return;
    }

    const targetRowIds = new Set(targetRows.map((item) => item.id));
    setFeedbackThreadsByResultId((current) => {
      const next = { ...current };
      targetRows.forEach((item) => {
        next[item.id] = thread;
      });
      return next;
    });

    if (shouldUpdateActiveThread && activeFeedbackThreadIdRef.current === thread.id) {
      setActiveFeedbackThread(thread);
    } else if (!activeFeedbackThreadIdRef.current && allowActivateDrawerThread && activeFeedbackResultIdRef.current && targetRowIds.has(activeFeedbackResultIdRef.current)) {
      setActiveFeedbackThread(thread);
    }

    let changed = false;
    const nextResults = currentResults.map((item) => {
      if (!targetRowIds.has(item.id)) return item;
      const nextFeedbackStatus = thread.status === 'resolved_incorrect' ? 'incorrect' : 'none';
      const nextFeedbackAt = nextFeedbackStatus === 'incorrect' ? (item.feedback_at || new Date().toISOString()) : null;
      const nextFeedbackNote = nextFeedbackStatus === 'incorrect'
        ? (fallbackNote || thread.summary || item.feedback_note || null)
        : null;
      if (
        item.feedback_status === nextFeedbackStatus
        && item.feedback_note === nextFeedbackNote
        && ((item.feedback_at || null) === (nextFeedbackAt || null) || nextFeedbackStatus !== 'incorrect')
      ) {
        return item;
      }
      changed = true;
      return {
        ...item,
        feedback_status: nextFeedbackStatus,
        feedback_at: nextFeedbackAt,
        feedback_note: nextFeedbackNote,
      };
    });

    if (changed) {
      onAuditResultsChange(nextResults);
    }
  };

  const feedbackTargetIdsSignature = useMemo(
    () => auditResults.map((result) => result.id).join('|'),
    [auditResults],
  );

  useEffect(() => {
    void refreshFeedbackThreadSummaries(auditResults);
    return () => {
    };
  }, [projectId, feedbackTargetIdsSignature, selectedAuditVersion, auditStatus?.audit_version]);

  useEffect(() => {
    if (!projectId) return;
    const version = selectedAuditVersion ?? auditStatus?.audit_version ?? null;
    if (version === null || version === undefined) return;

    const controller = createFeedbackThreadStreamController({
      projectId,
      version,
      onThreadUpsert: (thread) => {
        applyFeedbackThreadUpdate(thread, {
          updateActiveThread: false,
          allowActivateDrawerThread: true,
        });
      },
      onError: (message) => {
        if (message) {
          console.error(message);
        }
      },
    });
    controller.start();

    return () => {
      controller.stop();
    };
  }, [projectId, selectedAuditVersion, auditStatus?.audit_version]);

  useEffect(() => {
    if (!projectId || !feedbackDrawerOpen || !activeFeedbackThread?.id) return;
    const version = activeFeedbackThread.audit_version ?? selectedAuditVersion ?? auditStatus?.audit_version ?? null;
    if (version === null || version === undefined) return;

    const controller = createFeedbackThreadStreamController({
      projectId,
      version,
      threadId: activeFeedbackThread.id,
      onThreadUpsert: (thread) => {
        applyFeedbackThreadUpdate(thread, { updateActiveThread: true });
      },
      onMessageCreated: (message, meta) => {
        if (!meta?.threadId) return;
        appendActiveFeedbackMessage(meta.threadId, message);
      },
      onError: (message) => {
        if (message) {
          console.error(message);
        }
      },
    });
    controller.start();

    return () => {
      controller.stop();
    };
  }, [projectId, feedbackDrawerOpen, activeFeedbackThread?.id, activeFeedbackThread?.audit_version, selectedAuditVersion, auditStatus?.audit_version]);

  const unresolvedCounts = useMemo(() => ({
    index: auditResults.filter((result) => normalizeIssueType(result.type) === 'index' && !result.is_resolved).length,
    dimension: auditResults.filter((result) => normalizeIssueType(result.type) === 'dimension' && !result.is_resolved).length,
    material: auditResults.filter((result) => normalizeIssueType(result.type) === 'material' && !result.is_resolved).length,
  }), [auditResults]);

  const totalCount = auditResults.length;

  const reportDownloadUrl = projectId
    ? api.downloadPdfReport(projectId, selectedAuditVersion || auditStatus?.audit_version || undefined)
    : '#';

  const selectedVersionMeta = selectedAuditVersion !== null
    ? auditHistory.find((item) => item.version === selectedAuditVersion) || null
    : null;
  const selectedVersionDisplayCount = selectedVersionMeta?.grouped_count ?? selectedVersionMeta?.count ?? totalCount;
  const reportPresentation = resolveAuditReportPresentation(auditStatus, selectedVersionMeta);

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

  const openIssueDrawing = async (
    result: AuditResult,
    options?: { preserveView?: boolean },
  ) => {
    if (!projectId) return;
    const requestId = previewRequestRef.current + 1;
    previewRequestRef.current = requestId;
    setActionError('');

    try {
      let preview: Awaited<ReturnType<typeof api.getAuditResultPreview>> & { extra_source_anchors?: any[]; extra_target_anchors?: any[] };
      if (result.issue_ids && result.issue_ids.length > 1) {
        preview = await api.batchAuditResultPreview(projectId, result.issue_ids);
      } else {
        const previewId = result.issue_ids && result.issue_ids.length > 0 ? result.issue_ids[0] : result.id;
        preview = await api.getAuditResultPreview(projectId, previewId);
      }
      if (previewRequestRef.current !== requestId) return;

      if (!options?.preserveView) {
        setPreviewView('a');
      }
      setSelectedPreview({
        issueId: result.id,
        drawingA: resolvePreviewDrawing(preview.source),
        drawingB: resolvePreviewDrawing(preview.target),
        missingReason: preview.missing_reason,
        extraSourceAnchors: preview.extra_source_anchors || [],
        extraTargetAnchors: preview.extra_target_anchors || [],
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

  const syncAuditResultFromFeedbackThread = (
    resultId: string,
    thread: FeedbackThread,
    fallbackNote?: string | null,
  ) => {
    applyFeedbackThreadUpdate(thread, { fallbackNote, sourceResultId: resultId });
  };

  const appendActiveFeedbackMessage = (threadId: string, message: FeedbackThreadMessage) => {
    setActiveFeedbackThread((current) => {
      if (!current || current.id !== threadId) return current;
      if (current.messages.some((item) => item.id === message.id)) {
        return current;
      }
      return {
        ...current,
        messages: [...current.messages, message],
      };
    });
  };

  const openFeedbackThread = async (result: AuditResult) => {
    if (!projectId) return;
    const targetResultId = result.id;
    setFeedbackDrawerOpen(true);
    setActiveFeedbackResultId(result.id);
    setActiveFeedbackThread(null);
    setFeedbackThreadLoading(true);
    setFeedbackThreadError('');

    try {
      const thread = await api.getFeedbackThreadByResult(projectId, targetResultId, {
        auditVersion: selectedAuditVersion ?? auditStatus?.audit_version ?? undefined,
      });
      setActiveFeedbackThread(thread);
      syncAuditResultFromFeedbackThread(result.id, thread, result.feedback_note);
    } catch (error: any) {
      const status = error?.response?.status;
      if (status === 404) {
        setActiveFeedbackThread(null);
      } else {
        console.error('加载误报反馈会话失败', error);
        setFeedbackThreadError('这条反馈会话加载失败了，请稍后再试。');
      }
    } finally {
      setFeedbackThreadLoading(false);
    }
  };

  const handleSubmitFeedbackMessage = async (payload: { content: string; images: File[] }) => {
    if (!projectId || !activeFeedbackResultId) return;
    const activeResult = auditResults.find((item) => item.id === activeFeedbackResultId);
    if (!activeResult) return;

    setFeedbackThreadSubmitting(true);
    setFeedbackThreadError('');

    try {
      let thread: FeedbackThread;
      const targetResultId = activeResult.id;
      if (activeFeedbackThread) {
        thread = await api.appendFeedbackThreadMessage(projectId, activeFeedbackThread.id, payload);
      } else {
        thread = await api.createFeedbackThread(projectId, targetResultId, { message: payload.content, images: payload.images }, {
          auditVersion: selectedAuditVersion ?? auditStatus?.audit_version ?? undefined,
        });
      }
      setActiveFeedbackThread(thread);
      syncAuditResultFromFeedbackThread(activeResult.id, thread, payload.content);
    } catch (error: any) {
      console.error('提交误报反馈消息失败', error);
      if (error?.response?.data?.detail) {
        setFeedbackThreadError(String(error.response.data.detail));
      } else {
        setFeedbackThreadError('这条消息没有发成功，请稍后再试。');
      }
    } finally {
      setFeedbackThreadSubmitting(false);
    }
  };

  const handleRevokeFeedbackFromDrawer = async () => {
    if (!activeFeedbackResultId) return;
    const activeResult = auditResults.find((item) => item.id === activeFeedbackResultId);
    if (!activeResult) return;

    setFeedbackThreadSubmitting(true);
    setFeedbackThreadError('');
    try {
      await handleToggleFeedback(activeResult, 'none');
      setActiveFeedbackThread((current) => current ? {
        ...current,
        status: 'open',
        learning_decision: current.learning_decision === 'accepted_for_learning' ? 'pending' : current.learning_decision,
      } : current);
      setFeedbackThreadsByResultId((current) => {
        const next = { ...current };
        if (next[activeResult.id]) {
          next[activeResult.id] = {
            ...next[activeResult.id],
            status: 'open',
            learning_decision: next[activeResult.id].learning_decision === 'accepted_for_learning'
              ? 'pending'
              : next[activeResult.id].learning_decision,
          };
        }
        return next;
      });
    } catch {
      setFeedbackThreadError('撤销误报失败，请稍后再试。');
    } finally {
      setFeedbackThreadSubmitting(false);
    }
  };

  const selectedIssue = selectedPreview
    ? auditResults.find((item) => item.id === selectedPreview.issueId) || null
    : null;
  const activeFeedbackResult = activeFeedbackResultId
    ? auditResults.find((item) => item.id === activeFeedbackResultId) || null
    : null;
  const reportRunning = isAuditReportRunning(projectStatus, auditStatus);
  const selectedIssueSignature = buildIssuePreviewSignature(selectedIssue);

  useEffect(() => {
    if (!selectedPreview || !selectedIssue || !projectId) {
      selectedIssueSignatureRef.current = '';
      return;
    }

    const previousSignature = selectedIssueSignatureRef.current;
    selectedIssueSignatureRef.current = selectedIssueSignature;
    if (!previousSignature || previousSignature === selectedIssueSignature) {
      return;
    }
    void openIssueDrawing(selectedIssue, { preserveView: true });
  }, [projectId, selectedPreview, selectedIssue, selectedIssueSignature]);

  return (
    <div className="w-full space-y-8">
      <div className="space-y-6">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h2 className="text-[24px] font-semibold flex items-center gap-2">
              {reportPresentation.tone === 'error' ? (
                <AlertCircle className="h-6 w-6 text-destructive" />
              ) : reportPresentation.tone === 'warning' ? (
                <AlertCircle className="h-6 w-6 text-warning" />
              ) : (
                <CheckCircle2 className="h-6 w-6 text-success" />
              )}
              {reportPresentation.title}
            </h2>
            <p className="text-[14px] text-muted-foreground mt-1 text-balance">
              {reportPresentation.description}
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
                    <th className="w-[132px] px-2 py-3 text-center text-[12px] font-semibold text-foreground whitespace-nowrap">误报</th>
                  </tr>
                </thead>
                <tbody>
                  {auditResults.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-12 text-center text-[14px] text-muted-foreground">
                        {reportRunning ? '审图正在进行，问题将陆续出现。' : '当前这一轮还没有发现问题。'}
                      </td>
                    </tr>
                  ) : auditResults.map((result) => {
                    const isResolved = Boolean(result.is_resolved);
                    const isPending = Boolean(pendingIds[result.id]);
                    const isActive = selectedPreview?.issueId === result.id;
                    const isIncorrectFeedback = result.feedback_status === 'incorrect';
                    const feedbackThread = feedbackThreadsByResultId[result.id];
                    const compactThreadStatus = feedbackThread ? getThreadStatusLabel(feedbackThread.status) : null;
                    const compactLearningStatus = feedbackThread && feedbackThread.learning_decision !== 'pending'
                      ? getLearningDecisionLabel(feedbackThread.learning_decision)
                      : null;

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
                          <div className="flex flex-col items-center gap-1.5">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon-sm"
                              className={`rounded-none shadow-none ${
                                isIncorrectFeedback
                                  ? 'bg-destructive/10 text-destructive hover:bg-destructive/15 hover:text-destructive'
                                  : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                              }`}
                              disabled={isPending}
                              aria-label={`${isIncorrectFeedback ? '查看误报反馈' : '提交误报反馈'}：${result.sheet_no_a || '未命名图纸'}`}
                              title={isIncorrectFeedback ? '查看误报反馈会话' : '反馈为误报'}
                              onClick={() => { void openFeedbackThread(result); }}
                            >
                              <Flag className="w-4 h-4" />
                            </Button>
                            {compactThreadStatus ? (
                              <div className="max-w-[112px] space-y-0.5 text-center leading-4">
                                <div className="text-[10px] font-medium text-foreground">{compactThreadStatus}</div>
                                {compactLearningStatus ? (
                                  <div className="text-[10px] text-muted-foreground">{compactLearningStatus}</div>
                                ) : null}
                              </div>
                            ) : isIncorrectFeedback ? (
                              <div className="max-w-[112px] text-[10px] text-muted-foreground leading-4">
                                已标记误报
                              </div>
                            ) : null}
                          </div>
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
              extraSourceAnchors={selectedPreview.extraSourceAnchors}
              extraTargetAnchors={selectedPreview.extraTargetAnchors}
              activeView={previewView}
              onViewChange={setPreviewView}
              onClose={() => setSelectedPreview(null)}
            />
          ) : null}
        </div>
      </div>
      <FeedbackThreadDrawer
        open={feedbackDrawerOpen}
        onOpenChange={(open) => {
          setFeedbackDrawerOpen(open);
          if (!open) {
            setFeedbackThreadError('');
            setFeedbackThreadLoading(false);
          }
        }}
        result={activeFeedbackResult}
        thread={activeFeedbackThread}
        loading={feedbackThreadLoading}
        submitting={feedbackThreadSubmitting}
        error={feedbackThreadError}
        onSubmitMessage={handleSubmitFeedbackMessage}
        onRevokeIncorrect={handleRevokeFeedbackFromDrawer}
      />
    </div>
  );
}
