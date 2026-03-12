import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { CheckCircle, Download, X, AlertCircle, Database, RefreshCw, Play, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import * as api from '@/api';
import type { Project, Category, CatalogItem, Drawing, JsonData, AuditResult, AuditStatus, ThreeLineMatch, ThreeLineItem, MatchFilter } from '@/types';
import {
  AUDIT_PROVIDER_STORAGE_KEY,
  DEFAULT_AUDIT_PROVIDER_MODE,
  type AuditEvent,
  type AuditHistoryItem,
} from '@/types/api';

// Layout & UI Components
import AppLayout from '@/components/layout/AppLayout';
import TopHeader from '@/components/layout/TopHeader';
import AuditStepper from './ProjectDetail/components/AuditStepper';
import UploadCard from './ProjectDetail/components/UploadCard';
import CatalogTable from './ProjectDetail/components/CatalogTable';
import MatchTable from './ProjectDetail/components/MatchTable';
import ProjectStepAudit from './ProjectDetail/components/project-detail/ProjectStepAudit';
import AuditProgressDialog, {
  AuditProgressPill,
  getAuditProviderLabel,
} from './ProjectDetail/components/AuditProgressDialog';
import { createAuditEventStreamController } from './ProjectDetail/components/auditEventStream';
import { createAuditResultStreamController } from './ProjectDetail/components/auditResultStream';
import { useAuditProgressViewModel } from './ProjectDetail/components/useAuditProgressViewModel';

type AuditProgressUiState = 'minimized' | 'dismissed';

function getAuditProgressUiStateStorageKey(projectId?: string) {
  return projectId ? `ccad.auditProgress.uiState.${projectId}` : '';
}

function readAuditProgressUiState(projectId?: string): AuditProgressUiState | null {
  if (!projectId || typeof window === 'undefined') return null;
  const raw = window.sessionStorage.getItem(getAuditProgressUiStateStorageKey(projectId));
  return raw === 'minimized' || raw === 'dismissed' ? raw : null;
}

function persistAuditProgressUiState(projectId: string | undefined, nextState: AuditProgressUiState | null) {
  if (!projectId || typeof window === 'undefined') return;
  const key = getAuditProgressUiStateStorageKey(projectId);
  if (!nextState) {
    window.sessionStorage.removeItem(key);
    return;
  }
  window.sessionStorage.setItem(key, nextState);
}

export function isAuditRunActiveStatus(runStatus?: string | null): boolean {
  const normalized = (runStatus || '').toLowerCase();
  return ['planning', 'running', 'queued', 'pending'].includes(normalized);
}

export function hasAuditReachedTerminalState(
  runStatus?: string | null,
  status?: string | null,
): boolean {
  const normalizedRunStatus = (runStatus || '').toLowerCase();
  const normalizedStatus = (status || '').toLowerCase();
  return ['done', 'failed'].includes(normalizedRunStatus) || ['done', 'failed'].includes(normalizedStatus);
}

export function resolveProjectDetailStep(
  projectStatus?: string | null,
  currentAuditStatus?: AuditStatus | null,
): number {
  const normalizedProjectStatus = (projectStatus || '').toLowerCase();
  const normalizedAuditStatus = (currentAuditStatus?.status || '').toLowerCase();

  if (normalizedProjectStatus === 'new') return 0;

  if (
    normalizedProjectStatus === 'auditing'
    || normalizedProjectStatus === 'done'
    || normalizedAuditStatus === 'auditing'
    || isAuditRunActiveStatus(currentAuditStatus?.run_status)
  ) {
    return 2;
  }

  if (
    normalizedProjectStatus === 'catalog_locked'
    || normalizedProjectStatus === 'matching'
    || normalizedProjectStatus === 'ready'
  ) {
    return 1;
  }

  return 0;
}

export function upsertAuditResultRow(
  current: AuditResult[],
  incoming: AuditResult,
): AuditResult[] {
  let matched = false;
  const next = current.map((item) => {
    if (item.id !== incoming.id) return item;
    matched = true;
    return {
      ...item,
      ...incoming,
    };
  });
  return matched ? next : [...current, incoming];
}

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const initialAuditProgressUiState = readAuditProgressUiState(id);

  // Data States
  const [project, setProject] = useState<Project | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryCount, setCategoryCount] = useState<Record<string, number>>({});
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [jsonData, setJsonData] = useState<JsonData[]>([]);

  // Audit States
  const [auditStatus, setAuditStatus] = useState<AuditStatus | null>(null);
  const [auditResults, setAuditResults] = useState<AuditResult[]>([]);
  const [auditHistory, setAuditHistory] = useState<AuditHistoryItem[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditEventsError, setAuditEventsError] = useState('');
  const [auditEventsLoading, setAuditEventsLoading] = useState(false);
  const [selectedAuditVersion, setSelectedAuditVersion] = useState<number | null>(null);
  const [threeLineMatch, setThreeLineMatch] = useState<ThreeLineMatch | null>(null);

  // UI States
  const [currentStep, setCurrentStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [uploadingMenu, setUploadingMenu] = useState(false);
  const [uploadingPdf, setUploadingPdf] = useState(false);
  const [uploadingDwg, setUploadingDwg] = useState(false);
  const [menuUploadProgress, setMenuUploadProgress] = useState(0);
  const [pdfUploadProgress, setPdfUploadProgress] = useState(0);
  const [dwgUploadProgress, setDwgUploadProgress] = useState(0);
  const [pdfUploadProgressText, setPdfUploadProgressText] = useState('上传进度');
  const [dwgUploadProgressText, setDwgUploadProgressText] = useState('上传进度');
  const [startingAudit, setStartingAudit] = useState(false);
  const [isIncompleteAuditConfirmOpen, setIsIncompleteAuditConfirmOpen] = useState(false);
  const [isAuditInlinePreviewOpen, setIsAuditInlinePreviewOpen] = useState(false);
  const [isAuditProgressDialogOpen, setIsAuditProgressDialogOpen] = useState(false);
  const [isAuditProgressMinimized, setIsAuditProgressMinimized] = useState(initialAuditProgressUiState === 'minimized');
  const [isAuditProgressDismissed, setIsAuditProgressDismissed] = useState(initialAuditProgressUiState === 'dismissed');
  const [awaitingAuditStatusSync, setAwaitingAuditStatusSync] = useState(false);
  const [previewDrawing, setPreviewDrawing] = useState<{
    sheetNo: string;
    sheetName: string;
    pageIndex: number | null;
    imageUrl: string;
  } | null>(null);
  const [previewScale, setPreviewScale] = useState(1);
  const [previewOffset, setPreviewOffset] = useState({ x: 0, y: 0 });
  const [isPreviewPanning, setIsPreviewPanning] = useState(false);
  const previewViewportRef = useRef<HTMLDivElement | null>(null);
  const panLastPointRef = useRef<{ x: number; y: number } | null>(null);

  // Catalog Edit States
  const [isCatalogEditing, setIsCatalogEditing] = useState(false);
  const [catalogDraft, setCatalogDraft] = useState<{ id?: string, sheet_no: string, sheet_name: string }[]>([]);
  const [catalogSaving, setCatalogSaving] = useState(false);
  const [catalogEditError, setCatalogEditError] = useState('');
  const [showCatalogUploadCard, setShowCatalogUploadCard] = useState(true);

  // Match Table States
  const [matchFilter, setMatchFilter] = useState<MatchFilter>('all');

  // Generic Error State
  const [error, setError] = useState('');

  const loadSeqRef = useRef(0);
  const auditEventsSinceIdRef = useRef<number | null>(null);
  const auditEventsVersionRef = useRef<number | null>(null);
  const auditCompletionRefreshNeededRef = useRef(false);

  useEffect(() => {
    if (id) loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (!id) return;
    const persistedState = readAuditProgressUiState(id);
    setIsAuditProgressDialogOpen(false);
    setIsAuditProgressMinimized(persistedState === 'minimized');
    setIsAuditProgressDismissed(persistedState === 'dismissed');
  }, [id]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.removeItem(AUDIT_PROVIDER_STORAGE_KEY);
  }, []);

  useEffect(() => {
    if (!id || (currentStep !== 2)) return;
    let stopped = false;
    let timer: number | undefined;

    const syncAuditStatus = async () => {
      if (stopped) return;
      try {
        const latest = await api.getAuditStatus(id);
        setAuditStatus(latest);
        const reachedTerminalState = hasAuditReachedTerminalState(latest.run_status, latest.status);
        if (reachedTerminalState) {
          stopped = true;
          const shouldRefreshCompletedAudit = auditCompletionRefreshNeededRef.current;
          auditCompletionRefreshNeededRef.current = false;

          if (latest.run_status === 'failed' || latest.status === 'failed') {
            setError(`审核失败: ${latest.error}`);
          }

          if (shouldRefreshCompletedAudit) {
            setSelectedAuditVersion(null);
            await loadData();
          }
        }
      } catch (error) {
        console.error('获取审核状态失败', error);
      }
    };

    void syncAuditStatus();
    timer = window.setInterval(syncAuditStatus, 2000);
    return () => {
      stopped = true;
      if (timer) window.clearInterval(timer);
    };
  }, [id, currentStep]);

  useEffect(() => {
    if (currentStep !== 2) {
      setIsAuditInlinePreviewOpen(false);
    }
  }, [currentStep]);

  const auditRunStatus = (auditStatus?.run_status || '').toLowerCase();
  const auditStatusValue = (auditStatus?.status || '').toLowerCase();
  const isAuditRunning = startingAudit
    || project?.status === 'auditing'
    || auditStatusValue === 'auditing'
    || isAuditRunActiveStatus(auditRunStatus);
  const shouldShowAuditProgress = isAuditRunning || awaitingAuditStatusSync;
  const currentAuditProviderLabel = getAuditProviderLabel(auditStatus?.provider_mode || DEFAULT_AUDIT_PROVIDER_MODE);
  const auditProgressViewModel = useAuditProgressViewModel({
    auditStatus,
    events: auditEvents,
    providerLabel: currentAuditProviderLabel,
  });

  useEffect(() => {
    if (isAuditRunning) {
      auditCompletionRefreshNeededRef.current = true;
    }
  }, [isAuditRunning]);

  useEffect(() => {
    if (!shouldShowAuditProgress) {
      setIsAuditProgressDialogOpen(false);
      setAuditEvents([]);
      setAuditEventsError('');
      setAuditEventsLoading(false);
      auditEventsSinceIdRef.current = null;
      auditEventsVersionRef.current = null;
      return;
    }
    if (isAuditProgressDismissed || isAuditProgressMinimized) return;
    setIsAuditProgressDialogOpen(true);
  }, [shouldShowAuditProgress, isAuditProgressDismissed, isAuditProgressMinimized]);

  useEffect(() => {
    if (isAuditRunning || auditRunStatus === 'done' || auditRunStatus === 'failed') {
      setAwaitingAuditStatusSync(false);
    }
  }, [isAuditRunning, auditRunStatus]);

  useEffect(() => {
    if (loading || !project) return;
    if (shouldShowAuditProgress) return;
    // 当前没有运行中的审核时，清掉记忆，保证下一次新启动审核会自动弹窗。
    persistAuditProgressUiState(id, null);
  }, [id, loading, project, shouldShowAuditProgress]);

  useEffect(() => {
    if (!id || !shouldShowAuditProgress) return;

    const version = auditStatus?.audit_version ?? selectedAuditVersion ?? null;
    if (version === null || version === undefined) return;

    if (auditEventsVersionRef.current !== version) {
      setAuditEvents([]);
      auditEventsSinceIdRef.current = null;
    }

    auditEventsVersionRef.current = version;
    const controller = createAuditEventStreamController({
      projectId: id,
      version,
      onEvents: (events) => {
        setAuditEvents(events);
        const latest = events[events.length - 1];
        if (latest) {
          auditEventsSinceIdRef.current = latest.id;
        }
      },
      onError: (message) => {
        setAuditEventsError(message);
      },
      onLoadingChange: (loading) => {
        setAuditEventsLoading(loading);
      },
    });
    controller.start();

    return () => {
      controller.stop();
    };
  }, [id, shouldShowAuditProgress, auditStatus?.audit_version, selectedAuditVersion]);

  useEffect(() => {
    if (!id || currentStep !== 2 || !shouldShowAuditProgress) return;
    const liveVersion = auditStatus?.audit_version ?? null;
    if (liveVersion === null || liveVersion === undefined) return;
    if (selectedAuditVersion !== null && selectedAuditVersion !== liveVersion) return;

    let stopped = false;
    const bootstrap = async () => {
      try {
        const latest = await api.getAuditResults(id, { version: liveVersion, view: 'grouped' });
        if (stopped) return;
        setAuditResults(latest);
      } catch (error) {
        console.error('初始化增量结果失败', error);
      }
    };
    void bootstrap();

    const controller = createAuditResultStreamController({
      projectId: id,
      version: liveVersion,
      onUpsert: ({ row }) => {
        setAuditResults((current) => upsertAuditResultRow(current, row));
      },
      onSummary: () => {
        // 汇总事件用于统计对账，当前页面以列表实时计算为准。
      },
    });
    controller.start();

    return () => {
      stopped = true;
      controller.stop();
    };
  }, [id, currentStep, shouldShowAuditProgress, auditStatus?.audit_version, selectedAuditVersion]);

  useEffect(() => {
    if (!previewDrawing) return;
    const handleEscClose = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setPreviewDrawing(null);
      }
    };
    window.addEventListener('keydown', handleEscClose);
    return () => window.removeEventListener('keydown', handleEscClose);
  }, [previewDrawing]);

  const loadData = async (preferredAuditVersion?: number | null) => {
    if (!id) return;
    const seq = ++loadSeqRef.current;
    try {
      setLoading(true);
      const [proj, cats, allProjs, cat, drws, js, status, history, threeLine] = await Promise.all([
        api.getProject(id),
        api.getCategories(),
        api.getProjects(),
        api.getCatalog(id),
        api.getDrawings(id),
        api.getJsonDataList(id),
        api.getAuditStatus(id),
        api.getAuditHistory(id).catch(() => []),
        api.getThreeLineMatch(id).catch(() => null)
      ]);
      if (seq !== loadSeqRef.current) return;
      setProject(proj);
      setCategories(cats);

      const counts: Record<string, number> = { all: allProjs.length };
      cats.forEach(c => {
        counts[c.id] = allProjs.filter(p => p.category === c.id).length;
      });
      setCategoryCount(counts);

      setCatalog(cat);
      setShowCatalogUploadCard(cat.length === 0);
      setDrawings(drws);
      setJsonData(js);
      setAuditStatus(status);
      const historyList = (Array.isArray(history) ? history : []) as AuditHistoryItem[];
      setAuditHistory(historyList);
      const effectiveVersion = (() => {
        if (preferredAuditVersion !== null && preferredAuditVersion !== undefined) {
          return preferredAuditVersion;
        }
        if (selectedAuditVersion !== null && historyList.some((item) => item.version === selectedAuditVersion)) {
          return selectedAuditVersion;
        }
        if (status.audit_version !== null && status.audit_version !== undefined) return status.audit_version;
        return historyList[0]?.version ?? null;
      })();
      setSelectedAuditVersion(effectiveVersion);
      const results = await api.getAuditResults(id, {
        view: 'grouped',
        ...(effectiveVersion !== null ? { version: effectiveVersion } : {}),
      });
      if (seq !== loadSeqRef.current) return;
      setAuditResults(results);
      setThreeLineMatch(threeLine);

      setCurrentStep(resolveProjectDetailStep(proj.status, status));
    } catch (err: any) {
      if (seq !== loadSeqRef.current) return;
      setError(err?.response?.data?.detail || err.message || '加载失败');
    } finally {
      if (seq === loadSeqRef.current) setLoading(false);
    }
  };

  // Upload Handlers
  const handleUploadMenu = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files?.length || !id) return;
    const file = e.target.files[0];
    const name = file.name.toLowerCase();
    const isPdf = file.type === 'application/pdf' || name.endsWith('.pdf');
    const isPng = file.type === 'image/png' || name.endsWith('.png');
    if (!isPdf && !isPng) {
      setError('目录上传仅支持 PDF 或 PNG 文件');
      e.target.value = '';
      return;
    }
    try {
      setUploadingMenu(true);
      setMenuUploadProgress(0);
      await api.uploadCatalog(id, file, {
        onUploadProgress: (percent) => setMenuUploadProgress(percent),
      });
      setMenuUploadProgress(100);
      await loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || '上传目录失败');
    } finally {
      setUploadingMenu(false);
      setMenuUploadProgress(0);
      e.target.value = '';
    }
  };

  const handleUploadPdf = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files?.length || !id) return;
    let progressPoller: number | undefined;
    try {
      setUploadingPdf(true);
      setPdfUploadProgress(0);
      setPdfUploadProgressText('上传与处理进度');
      progressPoller = window.setInterval(async () => {
        try {
          const progress = await api.getDrawingsUploadProgress(id);
          if (typeof progress.progress === 'number') setPdfUploadProgress(progress.progress);
          if (progress.message) setPdfUploadProgressText(progress.message);
        } catch {
          // Ignore temporary polling errors
        }
      }, 500);

      const files = Array.from(e.target.files);
      const isPngBatch = files.every(f => f.type === 'image/png' || f.name.toLowerCase().endsWith('.png'));

      if (isPngBatch && files.length >= 1) {
        await api.uploadDrawingsPng(id, files);
      } else {
        await api.uploadDrawings(id, files[0]);
      }

      try {
        const finalProgress = await api.getDrawingsUploadProgress(id);
        if (typeof finalProgress.progress === 'number') setPdfUploadProgress(finalProgress.progress);
        if (finalProgress.message) setPdfUploadProgressText(finalProgress.message);
      } catch {
        // ignore
      }
      setPdfUploadProgress(100);
      await loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || '上传图纸失败');
    } finally {
      if (progressPoller) clearInterval(progressPoller);
      setUploadingPdf(false);
      e.target.value = '';
    }
  };

  const handleUploadDwg = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files?.length || !id) return;
    // 支持文件夹模式：从选中的所有文件中过滤出 .dwg 文件（含子文件夹）
    const dwgFiles = Array.from(e.target.files).filter(f =>
      f.name.toLowerCase().endsWith('.dwg')
    );
    if (!dwgFiles.length) {
      setError('未找到 DWG 文件，请确认所选文件夹中包含 .dwg 文件');
      e.target.value = '';
      return;
    }
    let progressPoller: number | undefined;
    try {
      setUploadingDwg(true);
      setDwgUploadProgress(0);
      setDwgUploadProgressText('上传与处理进度');
      progressPoller = window.setInterval(async () => {
        try {
          const progress = await api.getDwgUploadProgress(id);
          if (typeof progress.progress === 'number') setDwgUploadProgress(progress.progress);
          if (progress.message) setDwgUploadProgressText(progress.message);
        } catch {
          // Ignore temporary polling errors to avoid breaking upload flow
        }
      }, 500);
      await api.uploadDwg(id, dwgFiles);
      try {
        const finalProgress = await api.getDwgUploadProgress(id);
        if (typeof finalProgress.progress === 'number') setDwgUploadProgress(finalProgress.progress);
        if (finalProgress.message) setDwgUploadProgressText(finalProgress.message);
      } catch {
        setDwgUploadProgress(100);
      }
      await loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || '上传DWG失败');
    } finally {
      if (progressPoller) window.clearInterval(progressPoller);
      setUploadingDwg(false);
      setDwgUploadProgress(0);
      setDwgUploadProgressText('上传进度');
      e.target.value = '';
    }
  };

  // Catalog Edit Operations
  const startEditingCatalog = () => {
    setIsCatalogEditing(true);
    setCatalogDraft(catalog.map(c => ({ id: c.id, sheet_no: c.sheet_no || '', sheet_name: c.sheet_name || '' })));
  };

  const saveCatalogChanges = async () => {
    if (!id) return;
    const valid = catalogDraft.filter(i => i.sheet_name.trim() || i.sheet_no.trim());
    try {
      setCatalogSaving(true);
      await api.updateCatalog(id, valid);
      setIsCatalogEditing(false);
      await loadData();
    } catch (err: any) {
      setCatalogEditError(err?.response?.data?.detail || '保存失败');
    } finally {
      setCatalogSaving(false);
    }
  };

  const handleLockCatalog = async () => {
    if (!id) return;
    try {
      await api.lockCatalog(id);
      await loadData();
      setCurrentStep(1);
    } catch (err: any) {
      setError(err?.response?.data?.detail || '锁定失败');
    }
  };

  const handleStartAudit = async (allowIncomplete: boolean = false) => {
    if (!id) return;
    if (!allowIncomplete && matchStats.missing > 0) {
      setIsIncompleteAuditConfirmOpen(true);
      return;
    }
    try {
      setIsIncompleteAuditConfirmOpen(false);
      setStartingAudit(true);
      setAwaitingAuditStatusSync(true);
      setIsAuditProgressDismissed(false);
      setIsAuditProgressMinimized(false);
      setIsAuditProgressDialogOpen(true);
      persistAuditProgressUiState(id, null);
      const started = await api.startAudit(id, {
        provider_mode: DEFAULT_AUDIT_PROVIDER_MODE,
        ...(allowIncomplete ? { allow_incomplete: true } : {}),
      });
      setSelectedAuditVersion(started.audit_version ?? null);
      setAuditResults([]);
      setAuditStatus((previous) => ({
        project_id: previous?.project_id || id,
        status: 'auditing',
        audit_version: started.audit_version ?? previous?.audit_version ?? null,
        current_step: '准备审图任务',
        progress: 0,
        total_issues: 0,
        run_status: 'planning',
        provider_mode: DEFAULT_AUDIT_PROVIDER_MODE,
        error: null,
        started_at: previous?.started_at ?? null,
        finished_at: null,
        scope_mode: null,
        scope_summary: null,
      }));
      await loadData(started.audit_version ?? null);
      setCurrentStep(2);
    } catch (err: any) {
      setAwaitingAuditStatusSync(false);
      setIsAuditProgressDialogOpen(false);
      setIsAuditProgressMinimized(false);
      setError(err?.response?.data?.detail || '启动审核失败');
    } finally {
      setStartingAudit(false);
    }
  };

  const handleSelectAuditVersion = async (version: number) => {
    if (!id) return;
    try {
      const results = await api.getAuditResults(id, { version, view: 'grouped' });
      setSelectedAuditVersion(version);
      setAuditResults(results);
    } catch (err: any) {
      setError(err?.response?.data?.detail || '切换审核版本失败');
    }
  };

  const handlePreviewDrawing = (item: ThreeLineItem) => {
    if (!id || !item.drawing?.id || !item.drawing?.png_path) return;
    setPreviewDrawing({
      sheetNo: item.sheet_no || item.drawing.sheet_no || '未命名图号',
      sheetName: item.sheet_name || item.drawing.sheet_name || '未命名图纸',
      pageIndex: item.drawing.page_index ?? null,
      imageUrl: api.getDrawingImageUrl(id, item.drawing.id, project?.cache_version),
    });
  };

  const handleManualCatalogMatch = async (payload: {
    catalogId: string;
    drawingId: string;
    sheetNo?: string | null;
    sheetName?: string | null;
  }) => {
    if (!id) return;
    try {
      await api.updateDrawing(id, payload.drawingId, {
        catalog_id: payload.catalogId,
        sheet_no: payload.sheetNo || undefined,
        sheet_name: payload.sheetName || undefined,
      });
      await loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || '目录匹配更新失败');
      throw err;
    }
  };

  const handleDeleteDrawing = async (drawingId: string) => {
    if (!id) return;
    try {
      await api.deleteDrawing(id, drawingId);
      await loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || '删除 PDF 图纸失败');
      throw err;
    }
  };

  const handleDeleteJson = async (jsonId: string) => {
    if (!id) return;
    try {
      await api.deleteJsonData(id, jsonId);
      await loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || '删除 DWG 数据失败');
      throw err;
    }
  };

  const handleBatchDeleteDrawings = async (drawingIds: string[]) => {
    if (!id || !drawingIds.length) return;
    try {
      await api.batchDeleteDrawings(id, drawingIds);
      await loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || '批量删除 PDF 图纸失败');
      throw err;
    }
  };

  const handleBatchDeleteJson = async (jsonIds: string[]) => {
    if (!id || !jsonIds.length) return;
    try {
      await api.batchDeleteJsonData(id, jsonIds);
      await loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || '批量删除 DWG 数据失败');
      throw err;
    }
  };

  const handleManualJsonCatalogBind = async (payload: { jsonId: string; catalogId: string }) => {
    if (!id) return;
    await api.bindJsonToCatalog(id, payload.jsonId, payload.catalogId);
    await loadData();
  };

  const clampPreviewScale = (value: number) => Math.min(5, Math.max(0.3, value));

  const zoomPreview = (factor: number, originX = 0, originY = 0) => {
    setPreviewScale(prev => {
      const next = clampPreviewScale(Number((prev * factor).toFixed(3)));
      if (next === prev) return prev;
      const ratio = next / prev;
      setPreviewOffset(offset => ({
        x: offset.x - originX * (ratio - 1),
        y: offset.y - originY * (ratio - 1),
      }));
      return next;
    });
  };

  const handlePreviewWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const viewport = previewViewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();
    const originX = e.clientX - rect.left - rect.width / 2;
    const originY = e.clientY - rect.top - rect.height / 2;
    zoomPreview(e.deltaY > 0 ? 0.92 : 1.08, originX, originY);
  };

  const handlePreviewMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    setIsPreviewPanning(true);
    panLastPointRef.current = { x: e.clientX, y: e.clientY };
  };

  useEffect(() => {
    if (!isPreviewPanning) return;
    const onMouseMove = (e: MouseEvent) => {
      if (!panLastPointRef.current) return;
      const dx = e.clientX - panLastPointRef.current.x;
      const dy = e.clientY - panLastPointRef.current.y;
      panLastPointRef.current = { x: e.clientX, y: e.clientY };
      setPreviewOffset(prev => ({ x: prev.x + dx, y: prev.y + dy }));
    };
    const onMouseUp = () => {
      setIsPreviewPanning(false);
      panLastPointRef.current = null;
    };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [isPreviewPanning]);

  useEffect(() => {
    if (!previewDrawing) return;
    setPreviewScale(1);
    setPreviewOffset({ x: 0, y: 0 });
    setIsPreviewPanning(false);
    panLastPointRef.current = null;
  }, [previewDrawing?.imageUrl]);

  useEffect(() => {
    if (!previewDrawing) return;
    const prevBodyOverflow = document.body.style.overflow;
    const prevHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prevBodyOverflow;
      document.documentElement.style.overflow = prevHtmlOverflow;
    };
  }, [previewDrawing]);

  if (loading || !project) {
    return (
      <AppLayout>
        <div className="flex h-[50vh] items-center justify-center">
          <RefreshCw className="h-8 w-8 animate-spin text-primary" />
        </div>
      </AppLayout>
    );
  }

  const category = categories.find(c => c.id === project.category);
  const statusMap: Record<string, { label: string; variant: 'default' | 'secondary' | 'success' | 'warning' | 'destructive' }> = {
    new: { label: '待开始', variant: 'secondary' },
    catalog_locked: { label: '目录已确认', variant: 'warning' },
    matching: { label: '匹配中', variant: 'warning' },
    ready: { label: '待审核', variant: 'warning' },
    auditing: { label: '审核中', variant: 'warning' },
    done: { label: '已完成', variant: 'success' },
  };

  const matchItems = threeLineMatch?.items || [];
  const unmatchedDrawings = drawings.filter(d => !d.catalog_id);
  const filteredMatchItems = matchItems.filter(i => filterMatch(i, matchFilter));
  const matchStats = {
    total: matchItems.length,
    ready: matchItems.filter(i => i.status === 'ready').length,
    missing: matchItems.filter(i => i.status !== 'ready').length,
    missing_png: matchItems.filter(i => i.status === 'missing_png').length,
    missing_json: matchItems.filter(i => i.status === 'missing_json').length,
    missing_all: matchItems.filter(i => i.status === 'missing_all').length,
  };
  const shouldShowCatalogUploadCard = showCatalogUploadCard || catalog.length === 0;

  function filterMatch(item: ThreeLineItem, filterDesc: MatchFilter) {
    if (filterDesc === 'all') return true;
    if (filterDesc === 'ready') return item.status === 'ready';
    if (filterDesc === 'missing') return item.status !== 'ready';
    return item.status === filterDesc;
  }

  const handleDeleteAuditVersion = async (version: number) => {
    if (!id) return;
    if (!window.confirm(`确认删除审核版本 v${version}？该操作不可恢复。`)) return;
    try {
      setError('');
      await api.deleteAuditVersion(id, version);
      await loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || '删除审核版本失败');
    }
  };

  return (
    <AppLayout
      categories={categories}
      categoryCount={categoryCount}
      showSidebar={false}
      fullWidth={currentStep === 2 && isAuditInlinePreviewOpen}
    >
      <TopHeader
        title={project.name}
        category={category}
        onBack={() => navigate('/')}
        statusInfo={statusMap[project.status] || { label: '未知', variant: 'default' }}
        isAuditing={project.status === 'auditing'}
        auditPill={shouldShowAuditProgress && isAuditProgressMinimized ? (
          <AuditProgressPill
            progress={Math.max(3, Math.min(99, auditProgressViewModel.pill.progress))}
            onClick={() => {
              setIsAuditProgressMinimized(false);
              setIsAuditProgressDialogOpen(true);
              setIsAuditProgressDismissed(false);
              persistAuditProgressUiState(id, null);
            }}
          />
        ) : undefined}
      />

      <div className="flex flex-col flex-1 pb-16 px-8 gap-6">
        <AuditStepper currentStep={currentStep} project={project} onStepClick={setCurrentStep} />

        {error && (
          <div className="bg-destructive/10 text-destructive border border-destructive/20 p-4 mb-6 text-sm flex items-center gap-2">
            <AlertCircle className="w-4 h-4" />
            {error}
            <Button variant="ghost" size="icon" onClick={() => setError('')} className="ml-auto h-6 w-6 rounded-none hover:bg-destructive/20 text-destructive">
              <X className="w-4 h-4" />
            </Button>
          </div>
        )}

        <div className="flex bg-white flex-col lg:flex-row gap-6 items-start relative animate-in fade-in duration-500">

          {/* Main content switches by currentStep */}
          {currentStep === 0 && (
            shouldShowCatalogUploadCard ? (
              <div className="w-full grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
                <div className="lg:col-span-2 min-w-0">
                  <CatalogTable
                    projectId={id}
                    catalog={catalog}
                    isLocked={project.status !== 'new'}
                    isEditing={isCatalogEditing}
                    draft={catalogDraft}
                    saving={catalogSaving}
                    error={catalogEditError}
                    onStartEdit={startEditingCatalog}
                    onCancelEdit={() => setIsCatalogEditing(false)}
                    onSaveEdit={saveCatalogChanges}
                    onAddRow={() => setCatalogDraft([...catalogDraft, { sheet_no: '', sheet_name: '' }])}
                    onRemoveRow={(idx) => setCatalogDraft(d => d.filter((_, i) => i !== idx))}
                    onUpdateField={(idx, field, val) => setCatalogDraft(d => { const n = [...d]; n[idx] = { ...n[idx], [field]: val }; return n; })}
                    onLock={handleLockCatalog}
                    onReupload={() => setShowCatalogUploadCard(true)}
                    reuploadDisabled={uploadingMenu}
                    doubleColumnView={false}
                  />
                </div>
                <div className="lg:col-span-1">
                  <UploadCard
                    className="max-w-none w-full"
                    title="步骤 1: 上传图纸目录"
                    description="支持上传包含目录的 PDF 或 PNG，系统会自动通过 AI 视觉识别将目录提取为结构化数据。"
                    uploadText="选择目录文件上传"
                    uploading={uploadingMenu}
                    uploadProgress={menuUploadProgress}
                    buttonClassName="bg-black text-white hover:bg-black/90"
                    onUpload={handleUploadMenu}
                    accept=".pdf,.png,image/png,application/pdf"
                  />
                </div>
              </div>
            ) : (
              <div className="w-full min-w-0">
                <CatalogTable
                  projectId={id}
                  catalog={catalog}
                  isLocked={project.status !== 'new'}
                  isEditing={isCatalogEditing}
                  draft={catalogDraft}
                  saving={catalogSaving}
                  error={catalogEditError}
                  onStartEdit={startEditingCatalog}
                  onCancelEdit={() => setIsCatalogEditing(false)}
                  onSaveEdit={saveCatalogChanges}
                  onAddRow={() => setCatalogDraft([...catalogDraft, { sheet_no: '', sheet_name: '' }])}
                  onRemoveRow={(idx) => setCatalogDraft(d => d.filter((_, i) => i !== idx))}
                  onUpdateField={(idx, field, val) => setCatalogDraft(d => { const n = [...d]; n[idx] = { ...n[idx], [field]: val }; return n; })}
                  onLock={handleLockCatalog}
                  onReupload={() => setShowCatalogUploadCard(true)}
                  reuploadDisabled={uploadingMenu}
                  doubleColumnView
                />
              </div>
            )
          )}

          {currentStep === 1 && (
            <div className="w-full flex flex-col gap-6">
              <div className="w-full grid grid-cols-1 xl:grid-cols-3 gap-6 items-start">
                <UploadCard
                  className="max-w-none"
                  compact
                  title="视觉图纸上传"
                  description=""
                  uploadText="上传 PNG/PDF 图纸"
                  uploading={uploadingPdf}
                  uploadProgress={pdfUploadProgress}
                  uploadProgressText={pdfUploadProgressText}
                  buttonClassName="bg-black text-white hover:bg-black/90"
                  onUpload={handleUploadPdf}
                  accept=".pdf,application/pdf,image/png,.png"
                  multiple
                />
                <UploadCard
                  className="max-w-none"
                  compact
                  title="DWG 数据上传"
                  description=""
                  uploadText="上传 DWG 文件"
                  uploading={uploadingDwg}
                  uploadProgress={dwgUploadProgress}
                  uploadProgressText={dwgUploadProgressText}
                  buttonClassName="bg-black text-white hover:bg-black/90"
                  onUpload={handleUploadDwg}
                  folderMode
                />
                <div className="bg-secondary/30 border border-border p-4 flex flex-col gap-3 rounded-none w-full">
                  <div className="text-center">
                    <h2 className="text-[18px] font-semibold text-foreground mb-1">匹配确认与审核启动</h2>
                  </div>

                  <div className="group relative border border-dashed border-border/80 bg-white p-4 text-center hover:border-primary/50 transition-colors duration-300">
                    <Play className="h-7 w-7 mx-auto text-primary mb-2 group-hover:scale-110 transition-transform duration-300" />
                    <h3 className="text-[13px] font-sans font-semibold mb-2 text-foreground">
                      确认无误后，启动审核
                    </h3>
                    <Label className="block">
                      <Button
                        onClick={handleStartAudit}
                        disabled={startingAudit || matchItems.length === 0}
                        className="rounded-none shadow-none bg-primary hover:bg-primary/90 text-[14px] h-10 px-4 w-full text-white"
                      >
                        {startingAudit ? (
                          <><RefreshCw className="mr-2 h-4 w-4 animate-spin" /> 处理中...</>
                        ) : '启动审核'}
                      </Button>
                    </Label>
                  </div>
                </div>
              </div>

              <div className="bg-white pb-1">
                <MatchTable
                  items={filteredMatchItems}
                  filter={matchFilter}
                  onFilterChange={setMatchFilter}
                  onPreviewDrawing={handlePreviewDrawing}
                  hasUploadedDrawings={drawings.length > 0}
                  unmatchedDrawings={unmatchedDrawings}
                  unmatchedJsons={threeLineMatch?.unmatched_jsons || []}
                  onManualCatalogMatch={handleManualCatalogMatch}
                  onManualJsonCatalogBind={handleManualJsonCatalogBind}
                  onDeleteDrawing={handleDeleteDrawing}
                  onDeleteJson={handleDeleteJson}
                  onBatchDeleteDrawings={handleBatchDeleteDrawings}
                  onBatchDeleteJson={handleBatchDeleteJson}
                  projectId={id}
                  cacheVersion={project?.cache_version}
                  stats={matchStats}
                />
              </div>
            </div>
          )}

          {currentStep === 2 && (
            <ProjectStepAudit
              projectId={id}
              projectStatus={project?.status || 'new'}
              projectCacheVersion={project?.cache_version}
              auditStatus={auditStatus}
              auditHistory={auditHistory}
              selectedAuditVersion={selectedAuditVersion}
              auditResults={auditResults}
              drawings={drawings}
              stageTitle={auditProgressViewModel.headline}
              onSelectAuditVersion={(version) => { void handleSelectAuditVersion(version); }}
              onRequestDeleteVersion={(version) => { void handleDeleteAuditVersion(version); }}
              onAuditResultsChange={setAuditResults}
              onInlinePreviewChange={setIsAuditInlinePreviewOpen}
            />
          )}
        </div>
      </div>

      {previewDrawing && (
        <>
          <div
            className="fixed inset-0 z-[60] bg-black/35 animate-in fade-in duration-200"
            onClick={() => setPreviewDrawing(null)}
          />
          <aside className="fixed right-0 top-0 z-[70] h-screen w-[92vw] max-w-[1320px] border-l border-border bg-white shadow-2xl animate-in slide-in-from-right-full duration-300">
            <div className="h-16 px-6 border-b border-border flex items-center justify-between">
              <div className="min-w-0">
                <h3 className="text-[16px] font-semibold truncate">{previewDrawing.sheetNo} - {previewDrawing.sheetName}</h3>
                <p className="text-[12px] text-muted-foreground">
                  {previewDrawing.pageIndex !== null ? `PDF 第 ${previewDrawing.pageIndex + 1} 页` : '已解析图纸预览'}
                </p>
              </div>
              <Button variant="ghost" size="icon" onClick={() => setPreviewDrawing(null)} className="rounded-none">
                <X className="w-4 h-4" />
              </Button>
            </div>
            <div className="h-[calc(100vh-64px)] bg-secondary/20 p-4 flex flex-col gap-3">
              <div
                ref={previewViewportRef}
                onWheel={handlePreviewWheel}
                onMouseDown={handlePreviewMouseDown}
                className={`relative flex-1 overflow-hidden border border-border bg-white ${isPreviewPanning ? 'cursor-grabbing' : 'cursor-grab'}`}
              >
                <img
                  src={previewDrawing.imageUrl}
                  alt={`${previewDrawing.sheetNo} 图纸预览`}
                  draggable={false}
                  onDragStart={(e) => e.preventDefault()}
                  className="absolute left-1/2 top-1/2 max-w-[96%] max-h-[96%] object-contain select-none pointer-events-none"
                  style={{
                    transform: `translate(-50%, -50%) translate(${previewOffset.x}px, ${previewOffset.y}px) scale(${previewScale})`,
                    transformOrigin: 'center center',
                  }}
                />
              </div>
              <div className="flex items-center justify-between gap-3 border-t border-border pt-3">
                <p className="text-[12px] text-muted-foreground">滚轮缩放，按住鼠标左键拖动画布</p>
                <div className="flex items-center gap-2">
                  <span className="text-[12px] text-muted-foreground min-w-[56px] text-right">{Math.round(previewScale * 100)}%</span>
                  <Button variant="outline" size="sm" className="rounded-none h-8 px-3 shadow-none hover:shadow-none" onClick={() => zoomPreview(0.9)}>
                    缩小
                  </Button>
                  <Button variant="outline" size="sm" className="rounded-none h-8 px-3 shadow-none hover:shadow-none" onClick={() => zoomPreview(1.1)}>
                    放大
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="rounded-none h-8 px-3 shadow-none hover:shadow-none"
                    onClick={() => {
                      setPreviewScale(1);
                      setPreviewOffset({ x: 0, y: 0 });
                    }}
                  >
                    重置
                  </Button>
                </div>
              </div>
            </div>
          </aside>
        </>
      )}

      {shouldShowAuditProgress && isAuditProgressDialogOpen ? (
        <AuditProgressDialog
          open
          progress={Math.max(3, Math.min(99, auditProgressViewModel.progress))}
          headline={auditProgressViewModel.headline}
          supportingText={auditProgressViewModel.supportingText}
          startedAt={auditProgressViewModel.startedAt}
          chief={auditProgressViewModel.chief}
          workerWall={auditProgressViewModel.workerWall}
          debugTimeline={auditProgressViewModel.debugTimeline}
          eventError={auditEventsError}
          eventLoading={auditEventsLoading}
          providerLabel={currentAuditProviderLabel}
          onMinimize={() => {
            setIsAuditProgressDialogOpen(false);
            setIsAuditProgressMinimized(true);
            persistAuditProgressUiState(id, 'minimized');
          }}
          onRequestClose={async (onStep) => {
            const pid = id || '';
            onStep('正在强制关闭并清理本次审图...');
            await api.stopAudit(pid);

            onStep('刷新页面数据...');
            setIsAuditProgressDialogOpen(false);
            setIsAuditProgressMinimized(false);
            setIsAuditProgressDismissed(true);
            persistAuditProgressUiState(id, 'dismissed');
            setAuditStatus(null);
            setAuditResults([]);
            setAuditHistory([]);
            setSelectedAuditVersion(null);
            await loadData();
          }}
        />
      ) : null}

      <AlertDialog
        open={isIncompleteAuditConfirmOpen}
        onOpenChange={(nextOpen) => {
          if (!startingAudit) setIsIncompleteAuditConfirmOpen(nextOpen);
        }}
      >
        <AlertDialogContent className="max-w-[560px] rounded-none border border-border bg-white p-0 shadow-lg">
          <AlertDialogHeader className="items-start gap-4 px-7 pt-7 text-left">
            <AlertDialogTitle className="text-[22px] font-semibold leading-none text-zinc-900">
              存在缺项，确认继续审核？
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[14px] leading-6 text-zinc-600">
              当前图纸三线匹配未完成。若带缺项继续审核，涉及缺页或缺数据的图纸可能出现漏检、误报，相关定位结果也可能不完整。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="px-7 pb-2 text-[14px] leading-7 text-zinc-700">
            <div>总数：<span className="font-medium text-zinc-900">{matchStats.total}</span></div>
            <div>就绪：<span className="font-medium text-zinc-900">{matchStats.ready}</span></div>
            <div>缺图纸：<span className="font-medium text-zinc-900">{matchStats.missing_png}</span></div>
            <div>缺数据：<span className="font-medium text-zinc-900">{matchStats.missing_json}</span></div>
            <div>都缺：<span className="font-medium text-zinc-900">{matchStats.missing_all}</span></div>
          </div>
          <AlertDialogFooter className="mt-5 flex-row justify-end gap-3 border-t border-zinc-100 px-7 py-5">
            <AlertDialogCancel
              disabled={startingAudit}
              className="h-10 rounded-none border-border bg-white px-6 text-[15px] font-medium text-zinc-700 hover:bg-secondary"
            >
              取消
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={(event) => {
                event.preventDefault();
                void handleStartAudit(true);
              }}
              disabled={startingAudit}
              className="h-10 rounded-none bg-primary px-6 text-[15px] font-medium text-white hover:bg-primary/90"
            >
              {startingAudit ? '处理中...' : '仍要带缺项启动'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

    </AppLayout>
  );
}
