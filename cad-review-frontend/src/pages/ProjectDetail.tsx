import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { CheckCircle, Download, X, AlertCircle, Database, RefreshCw, Play, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
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

// Layout & UI Components
import AppLayout from '@/components/layout/AppLayout';
import TopHeader from '@/components/layout/TopHeader';
import AuditStepper from './ProjectDetail/components/AuditStepper';
import UploadCard from './ProjectDetail/components/UploadCard';
import CatalogTable from './ProjectDetail/components/CatalogTable';
import MatchTable from './ProjectDetail/components/MatchTable';

const STAGE_FLOW = [
  { match: ['校验三线匹配'], title: '准备检查' },
  { match: ['构建图纸上下文'], title: '提取图纸信息' },
  { match: ['规划审核任务图'], title: '规划审核路径' },
  { match: ['索引核对'], title: '索引断链核对' },
  { match: ['尺寸核对'], title: '尺寸比对核查' },
  { match: ['材料核对'], title: '材料表验证' },
  { match: ['审核完成'], title: '生成报告' },
];

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

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
  const [clearingAudit, setClearingAudit] = useState(false);
  const [showClearAuditDialog, setShowClearAuditDialog] = useState(false);
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

  useEffect(() => {
    if (id) loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (!id || (currentStep !== 2)) return;
    let stopped = false;
    let timer: number | undefined;

    const syncAuditStatus = async () => {
      if (stopped) return;
      try {
        const latest = await api.getAuditStatus(id);
        setAuditStatus(latest);
        if (latest.run_status === 'done' || latest.status === 'done') {
          if (latest.audit_version) {
            const results = await api.getAuditResults(id, { version: latest.audit_version });
            setAuditResults(results);
          }
          stopped = true;
        } else if (latest.run_status === 'failed') {
          stopped = true;
          setError(`审核失败: ${latest.error}`);
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
    if (!previewDrawing) return;
    const handleEscClose = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setPreviewDrawing(null);
      }
    };
    window.addEventListener('keydown', handleEscClose);
    return () => window.removeEventListener('keydown', handleEscClose);
  }, [previewDrawing]);

  const loadData = async () => {
    if (!id) return;
    try {
      setLoading(true);
      const [proj, cats, allProjs, cat, drws, js, status, results, threeLine] = await Promise.all([
        api.getProject(id),
        api.getCategories(),
        api.getProjects(),
        api.getCatalog(id),
        api.getDrawings(id),
        api.getJsonDataList(id),
        api.getAuditStatus(id),
        api.getAuditResults(id),
        api.getThreeLineMatch(id).catch(() => null)
      ]);
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
      setAuditResults(results);
      setThreeLineMatch(threeLine);

      // Restore Steps
      if (proj.status === 'new') setCurrentStep(0);
      else if (proj.status === 'catalog_locked' || proj.status === 'matching' || proj.status === 'ready') setCurrentStep(1);
      else if (proj.status === 'auditing' || proj.status === 'done') setCurrentStep(2);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || '加载失败');
    } finally {
      setLoading(false);
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
          // Ignore temporary polling errors to avoid breaking upload flow
        }
      }, 500);
      await api.uploadDrawings(id, e.target.files[0]);
      try {
        const finalProgress = await api.getDrawingsUploadProgress(id);
        if (typeof finalProgress.progress === 'number') setPdfUploadProgress(finalProgress.progress);
        if (finalProgress.message) setPdfUploadProgressText(finalProgress.message);
      } catch {
        setPdfUploadProgress(100);
      }
      await loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || '上传图纸失败');
    } finally {
      if (progressPoller) window.clearInterval(progressPoller);
      setUploadingPdf(false);
      setPdfUploadProgress(0);
      setPdfUploadProgressText('上传进度');
      e.target.value = '';
    }
  };

  const handleUploadDwg = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files?.length || !id) return;
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
      await api.uploadDwg(id, Array.from(e.target.files));
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

  const handleStartAudit = async () => {
    if (!id) return;
    try {
      setStartingAudit(true);
      await api.startAudit(id);
      await loadData();
      setCurrentStep(2);
    } catch (err: any) {
      setError(err?.response?.data?.detail || '启动审核失败');
    } finally {
      setStartingAudit(false);
    }
  };

  const handleClearAuditReport = async () => {
    if (!id) return;
    try {
      setClearingAudit(true);
      await api.clearAuditReport(id);
      setShowClearAuditDialog(false);
      await loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || '清空审核报告失败');
    } finally {
      setClearingAudit(false);
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
    missing_json: matchItems.filter(i => i.status === 'missing_json').length
  };
  const shouldShowCatalogUploadCard = showCatalogUploadCard || catalog.length === 0;

  function filterMatch(item: ThreeLineItem, filterDesc: MatchFilter) {
    if (filterDesc === 'all') return true;
    if (filterDesc === 'ready') return item.status === 'ready';
    if (filterDesc === 'missing') return item.status !== 'ready';
    return item.status === filterDesc;
  }

  const getStageTitle = (status: AuditStatus | null) => {
    if (!status?.current_step) return '正在审核中';
    const activeStage = STAGE_FLOW.find(s => s.match.some(m => status.current_step.includes(m)));
    return activeStage ? activeStage.title : status.current_step;
  };

  return (
    <AppLayout categories={categories} categoryCount={categoryCount} showSidebar={false}>
      <TopHeader
        title={project.name}
        category={category}
        onBack={() => navigate('/')}
        statusInfo={statusMap[project.status] || { label: '未知', variant: 'default' }}
        isAuditing={project.status === 'auditing'}
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
                  accept="image/png,.pdf,.zip"
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
                  accept=".dwg"
                  multiple
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
                    <Button
                      onClick={handleStartAudit}
                      disabled={startingAudit || matchItems.length === 0}
                      className="rounded-none shadow-none bg-primary hover:bg-primary/90 text-[14px] h-10 px-4 w-full text-white"
                    >
                      {startingAudit ? (
                        <><RefreshCw className="mr-2 h-4 w-4 animate-spin" /> 处理中...</>
                      ) : '启动审核'}
                    </Button>
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
                  onManualCatalogMatch={handleManualCatalogMatch}
                  onDeleteDrawing={handleDeleteDrawing}
                  onDeleteJson={handleDeleteJson}
                  onBatchDeleteDrawings={handleBatchDeleteDrawings}
                  onBatchDeleteJson={handleBatchDeleteJson}
                  stats={matchStats}
                />
              </div>
            </div>
          )}

          {currentStep === 2 && (
            <div className="w-full space-y-8 animate-in fade-in duration-500 mx-auto">
              {project.status === 'auditing' ? (
                <Card className="rounded-none border-border shadow-none border p-16 text-center w-full bg-white">
                  <RefreshCw className="h-12 w-12 text-primary animate-spin mx-auto mb-6" />
                  <h3 className="text-[20px] font-semibold mb-3">AI 内核正在扫描核对</h3>
                  <p className="text-[14px] text-muted-foreground mb-8 text-balance">
                    正在持续深入挖掘分析，由于要进行庞大的交叉核对运算，这个过程可能需要几分钟。您可以先去喝杯咖啡。目前：{getStageTitle(auditStatus)}
                  </p>
                  <Progress value={auditStatus?.progress || 0} className="w-[300px] mx-auto h-1 bg-secondary [&>div]:bg-primary" />
                </Card>
              ) : (
                <div className="space-y-6">
                  <div className="flex justify-between items-center mb-6">
                    <div>
                      <h2 className="text-[24px] font-semibold flex items-center gap-2">
                        <CheckCircle className="h-6 w-6 text-success" />
                        审核报告就绪
                      </h2>
                      <p className="text-[14px] text-muted-foreground mt-1 text-balance">全部深度核查完成，您可以直观浏览异常项，也可以下载留存 PDF 报告。</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="outline"
                        onClick={() => setShowClearAuditDialog(true)}
                        className="rounded-none bg-white shadow-none h-10 px-4"
                      >
                        <Trash2 className="w-4 h-4 mr-2" />
                        清空审核报告
                      </Button>
                      <Button className="rounded-none bg-primary shadow-none h-10 w-[160px]">
                        <Download className="w-4 h-4 mr-2" />
                        导出详细报告
                      </Button>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    <Card className="rounded-none border-border shadow-none bg-secondary/10">
                      <CardContent className="p-6">
                        <p className="text-[13px] text-muted-foreground mb-2">发现异常总计</p>
                        <p className="text-[32px] font-semibold text-foreground leading-none">{auditStatus?.total_issues || 0}</p>
                      </CardContent>
                    </Card>
                    <Card className="rounded-none border-border shadow-none bg-destructive/5">
                      <CardContent className="p-6">
                        <p className="text-[13px] text-destructive/80 mb-2 flex items-center gap-1.5"><X className="w-4 h-4" />索引错误</p>
                        <p className="text-[32px] font-semibold text-destructive leading-none">{auditResults.filter(r => r.type === 'index').length}</p>
                      </CardContent>
                    </Card>
                    <Card className="rounded-none border-border shadow-none bg-warning/5">
                      <CardContent className="p-6">
                        <p className="text-[13px] text-warning-foreground mb-2 flex items-center gap-1.5"><AlertCircle className="w-4 h-4" />尺寸分歧</p>
                        <p className="text-[32px] font-semibold text-warning-foreground leading-none">{auditResults.filter(r => r.type === 'dimension').length}</p>
                      </CardContent>
                    </Card>
                    <Card className="rounded-none border-border shadow-none bg-info/5">
                      <CardContent className="p-6">
                        <p className="text-[13px] text-primary/80 mb-2 flex items-center gap-1.5"><Database className="w-4 h-4" />材料未对齐</p>
                        <p className="text-[32px] font-semibold text-primary leading-none">{auditResults.filter(r => r.type === 'material').length}</p>
                      </CardContent>
                    </Card>
                  </div>

                  <div className="space-y-4 pt-6">
                    {auditResults.map(res => (
                      <div key={res.id} className="p-6 bg-white border border-border flex items-start gap-4">
                        <Badge variant={res.severity === 'error' ? 'destructive' : 'warning'} className="rounded-none shrink-0 h-6 px-3">{res.type}</Badge>
                        <div className="flex-1">
                          <div className="flex gap-2 items-center mb-1.5">
                            <span className="text-[13px] font-medium bg-secondary px-2 py-0.5 text-foreground">{res.sheet_no_a}</span>
                            {res.sheet_no_b && (
                              <>
                                <X className="w-3 h-3 text-muted-foreground" />
                                <span className="text-[13px] font-medium bg-secondary px-2 py-0.5 text-foreground">{res.sheet_no_b}</span>
                              </>
                            )}
                          </div>
                          <p className="text-[14px] text-muted-foreground/90">{res.description}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
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

      <AlertDialog
        open={showClearAuditDialog}
        onOpenChange={(open) => {
          if (!clearingAudit) setShowClearAuditDialog(open);
        }}
      >
        <AlertDialogContent className="max-w-[560px] rounded-none border border-border bg-white p-0 shadow-lg">
          <AlertDialogHeader className="items-start gap-4 px-7 pt-7 text-left">
            <AlertDialogTitle className="text-[22px] font-semibold leading-none text-zinc-900">
              清空审核报告
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[14px] leading-6 text-zinc-600">
              将删除该项目现有审核结果与运行记录。该操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div className="mx-7 mt-5 rounded-none border border-border bg-secondary px-4 py-3.5 text-[14px] text-zinc-700">
            <span className="text-zinc-500">项目：</span>
            <span className="font-medium text-zinc-900">{project?.name || '-'}</span>
          </div>

          <AlertDialogFooter className="mt-7 flex-row justify-end gap-3 border-t border-zinc-100 px-7 py-5">
            <AlertDialogCancel
              disabled={clearingAudit}
              className="h-10 rounded-none border-border bg-white px-6 text-[15px] font-medium text-zinc-700 hover:bg-secondary"
            >
              取消
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleClearAuditReport}
              disabled={clearingAudit}
              className="h-10 rounded-none bg-red-600 px-6 text-[15px] font-semibold text-white hover:bg-red-700"
            >
              {clearingAudit ? '清空中...' : '确认清空'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AppLayout>
  );
}
