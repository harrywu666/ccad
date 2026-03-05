import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Upload, FileText, Image, Database,
  CheckCircle, AlertCircle, Download, Play, RefreshCw,
  Check, X, FileSearch, ArrowRight, LayoutDashboard,
  CloudUpload, FileCode2, Pencil, Save, Plus, Trash2
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import * as api from '@/api';
import type {
  Project,
  Category,
  CatalogItem,
  Drawing,
  JsonData,
  AuditResult,
  AuditStatus,
  ThreeLineMatch,
  ThreeLineItem,
} from '@/types';

const steps = [
  { id: 'catalog', name: '目录', description: '上传并确认图纸总目录', icon: FileText },
  { id: 'drawings', name: '图纸', description: '上传图纸长图纸PDF', icon: Image },
  { id: 'dwg', name: 'DWG数据', description: '解析精确尺寸数据', icon: Database },
  { id: 'match', name: '全息比对', description: '目录/图纸/数据的综合匹配', icon: FileSearch },
  { id: 'audit', name: '审核报告', description: '智能审阅错漏并生成报告', icon: LayoutDashboard },
];

const statusMap: Record<string, { label: string; variant: 'default' | 'secondary' | 'success' | 'warning' | 'destructive' }> = {
  new: { label: '待开始', variant: 'secondary' },
  catalog_locked: { label: '目录已确认', variant: 'warning' },
  matching: { label: '匹配中', variant: 'warning' },
  ready: { label: '待审核', variant: 'warning' },
  auditing: { label: '正在智能审核中...', variant: 'warning' },
  done: { label: '审核完成', variant: 'success' },
};

type CatalogDraftItem = {
  id?: string;
  sheet_no: string;
  sheet_name: string;
};

type MatchFilter = 'all' | 'ready' | 'missing' | 'missing_png' | 'missing_json' | 'missing_all';

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [jsonData, setJsonData] = useState<JsonData[]>([]);
  const [auditResults, setAuditResults] = useState<AuditResult[]>([]);
  const [auditStatus, setAuditStatus] = useState<AuditStatus | null>(null);
  const [threeLineMatch, setThreeLineMatch] = useState<ThreeLineMatch | null>(null);
  const [matchFilter, setMatchFilter] = useState<MatchFilter>('all');
  const [currentStep, setCurrentStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [isCatalogEditing, setIsCatalogEditing] = useState(false);
  const [catalogDraft, setCatalogDraft] = useState<CatalogDraftItem[]>([]);
  const [catalogSaving, setCatalogSaving] = useState(false);
  const [catalogEditError, setCatalogEditError] = useState('');
  const [editingDrawingId, setEditingDrawingId] = useState<string | null>(null);
  const [drawingDraft, setDrawingDraft] = useState({ catalog_id: '' });
  const [drawingSaveLoading, setDrawingSaveLoading] = useState(false);
  const [drawingEditError, setDrawingEditError] = useState('');

  useEffect(() => {
    if (id) loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const loadData = async () => {
    if (!id) return;
    try {
      const threeLine = await api.getThreeLineMatch(id).catch(() => null);
      const [proj, cats, cat, drws, js, status, results] = await Promise.all([
        api.getProject(id),
        api.getCategories(),
        api.getCatalog(id),
        api.getDrawings(id),
        api.getJsonDataList(id),
        api.getAuditStatus(id),
        api.getAuditResults(id),
      ]);
      setProject(proj);
      setCategories(cats);
      setCatalog(cat);
      setThreeLineMatch(threeLine);
      setCatalogDraft(
        cat.map(item => ({
          id: item.id,
          sheet_no: item.sheet_no || '',
          sheet_name: item.sheet_name || '',
        }))
      );
      setIsCatalogEditing(false);
      setCatalogEditError('');
      setEditingDrawingId(null);
      setDrawingDraft({ catalog_id: '' });
      setDrawingEditError('');
      setDrawings(drws);
      setJsonData(js);
      setAuditStatus(status);
      setAuditResults(results);

      if (proj.status === 'new') setCurrentStep(0);
      else if (proj.status === 'catalog_locked') setCurrentStep(1);
      else if (proj.status === 'matching') setCurrentStep(2);
      else if (proj.status === 'ready') setCurrentStep(3);
      else if (proj.status === 'auditing' || proj.status === 'done') setCurrentStep(4);
    } catch (error) {
      console.error('加载数据失败:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleUploadCatalog = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !id) return;
    setUploading(true);
    try {
      await api.uploadCatalog(id, file);
      await loadData();
    } catch (error) {
      console.error('上传目录失败:', error);
    } finally {
      setUploading(false);
    }
  };

  const handleLockCatalog = async () => {
    if (!id) return;
    try {
      await api.lockCatalog(id);
      await loadData();
    } catch (error) {
      console.error('锁定目录失败:', error);
    }
  };

  const startManualCatalogEdit = () => {
    setCatalogEditError('');
    if (catalog.length > 0) {
      setCatalogDraft(
        catalog.map(item => ({
          id: item.id,
          sheet_no: item.sheet_no || '',
          sheet_name: item.sheet_name || '',
        }))
      );
    } else {
      setCatalogDraft([{ sheet_no: '', sheet_name: '' }]);
    }
    setIsCatalogEditing(true);
  };

  const cancelManualCatalogEdit = () => {
    setCatalogDraft(
      catalog.map(item => ({
        id: item.id,
        sheet_no: item.sheet_no || '',
        sheet_name: item.sheet_name || '',
      }))
    );
    setCatalogEditError('');
    setIsCatalogEditing(false);
  };

  const updateCatalogDraftField = (index: number, field: 'sheet_no' | 'sheet_name', value: string) => {
    setCatalogDraft(prev =>
      prev.map((row, i) => (i === index ? { ...row, [field]: value } : row))
    );
  };

  const addCatalogDraftRow = () => {
    setCatalogDraft(prev => [...prev, { sheet_no: '', sheet_name: '' }]);
  };

  const removeCatalogDraftRow = (index: number) => {
    setCatalogDraft(prev => prev.filter((_, i) => i !== index));
  };

  const saveManualCatalogEdit = async () => {
    if (!id) return;

    const items = catalogDraft
      .map(row => ({
        id: row.id,
        sheet_no: row.sheet_no.trim(),
        sheet_name: row.sheet_name.trim(),
      }))
      .filter(row => row.sheet_no || row.sheet_name);

    if (items.length === 0) {
      setCatalogEditError('请至少保留一条目录数据。');
      return;
    }

    setCatalogSaving(true);
    setCatalogEditError('');
    try {
      await api.updateCatalog(id, items);
      await loadData();
    } catch (error) {
      console.error('保存目录失败:', error);
      setCatalogEditError('保存失败，请稍后重试。');
    } finally {
      setCatalogSaving(false);
    }
  };

  const handleUploadDrawings = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !id) return;
    setUploading(true);
    try {
      await api.uploadDrawings(id, file);
      await loadData();
    } catch (error) {
      console.error('上传图纸失败:', error);
    } finally {
      setUploading(false);
    }
  };

  const startEditDrawing = (drawing: Drawing) => {
    setEditingDrawingId(drawing.id);
    setDrawingDraft({
      catalog_id: drawing.catalog_id || '',
    });
    setDrawingEditError('');
  };

  const cancelEditDrawing = () => {
    setEditingDrawingId(null);
    setDrawingDraft({ catalog_id: '' });
    setDrawingEditError('');
  };

  const saveEditDrawing = async (drawingId: string) => {
    if (!id) return;

    setDrawingSaveLoading(true);
    setDrawingEditError('');
    try {
      if (!drawingDraft.catalog_id) {
        setDrawingEditError('请选择要匹配的目录项。');
        setDrawingSaveLoading(false);
        return;
      }

      await api.updateDrawing(id, drawingId, {
        catalog_id: drawingDraft.catalog_id,
      });
      await loadData();
    } catch (error) {
      console.error('手动修改图纸失败:', error);
      setDrawingEditError('保存失败，请稍后重试。');
    } finally {
      setDrawingSaveLoading(false);
    }
  };

  const handleUploadDwg = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0 || !id) return;
    setUploading(true);
    try {
      await api.uploadDwg(id, files);
      await loadData();
    } catch (error) {
      console.error('上传DWG失败:', error);
    } finally {
      setUploading(false);
    }
  };

  const handleStartAudit = async () => {
    if (!id) return;
    setUploading(true);
    try {
      await api.startAudit(id);
      const result = await api.runAudit(id);
      await loadData();
    } catch (error) {
      console.error('审核失败:', error);
    } finally {
      setUploading(false);
    }
  };

  const handleDownloadPdf = () => {
    if (!id) return;
    const url = api.downloadPdfReport(id);
    window.open(url, '_blank');
  };

  const handleDownloadExcel = () => {
    if (!id) return;
    const url = api.downloadExcelReport(id);
    window.open(url, '_blank');
  };

  const isStepComplete = (index: number) => {
    if (!project) return false;
    if (index === 0) return project.status !== 'new';
    if (index === 1) return project.status !== 'new' && project.status !== 'catalog_locked';
    if (index === 2) return project.status !== 'new' && project.status !== 'catalog_locked' && project.status !== 'matching';
    if (index === 3) return project.status === 'ready' || project.status === 'auditing' || project.status === 'done';
    if (index === 4) return project.status === 'done';
    return false;
  };

  const isStepActive = (index: number) => {
    if (!project) return false;
    return currentStep === index;
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50/50 dark:bg-zinc-950 flex flex-col items-center justify-center space-y-4">
        <RefreshCw className="h-10 w-10 animate-spin text-primary/70" />
        <p className="text-muted-foreground font-medium animate-pulse">正在进入工作流...</p>
      </div>
    );
  }

  const category = categories.find(c => c.id === project?.category);
  const statusInfo = statusMap[project?.status || 'new'];
  const isCatalogLocked = catalog.length > 0 && catalog[0]?.status === 'locked';
  const currentCatalogRows = isCatalogEditing ? catalogDraft : catalog;
  const unmatchedDrawings = drawings.filter(item => item.status !== 'matched');
  const fallbackMatchItems: ThreeLineItem[] = catalog.map(item => {
    const drawing = drawings.find(d => d.catalog_id === item.id) || null;
    const json = jsonData.find(j => j.catalog_id === item.id) || null;
    const hasPng = Boolean(drawing?.png_path);
    const hasJson = Boolean(json?.json_path);
    const status: ThreeLineItem['status'] = hasPng && hasJson
      ? 'ready'
      : !hasPng && hasJson
        ? 'missing_png'
        : hasPng && !hasJson
          ? 'missing_json'
          : 'missing_all';
    return {
      catalog_id: item.id,
      sheet_no: item.sheet_no,
      sheet_name: item.sheet_name,
      sort_order: item.sort_order,
      status,
      drawing: drawing
        ? {
            id: drawing.id,
            sheet_no: drawing.sheet_no,
            sheet_name: drawing.sheet_name,
            data_version: drawing.data_version,
            status: drawing.status,
            png_path: drawing.png_path,
            page_index: drawing.page_index,
          }
        : null,
      json: json
        ? {
            id: json.id,
            sheet_no: json.sheet_no,
            data_version: json.data_version,
            status: json.status,
            json_path: json.json_path,
            summary: json.summary,
            created_at: null,
          }
        : null,
    };
  });
  const matchItems = (threeLineMatch?.items || fallbackMatchItems).slice().sort((a, b) => a.sort_order - b.sort_order);
  const matchSummary = threeLineMatch?.summary || {
    total: matchItems.length,
    ready: matchItems.filter(item => item.status === 'ready').length,
    missing_png: matchItems.filter(item => item.status === 'missing_png').length,
    missing_json: matchItems.filter(item => item.status === 'missing_json').length,
    missing_all: matchItems.filter(item => item.status === 'missing_all').length,
  };
  const filteredMatchItems = matchItems.filter(item => {
    if (matchFilter === 'all') return true;
    if (matchFilter === 'ready') return item.status === 'ready';
    if (matchFilter === 'missing') return item.status !== 'ready';
    return item.status === matchFilter;
  });
  const canStartAudit = matchSummary.total > 0 && matchSummary.ready === matchSummary.total;
  const blockedReason = matchSummary.total === 0
    ? '请先锁定目录并上传图纸数据。'
    : `缺少数据：缺图纸 ${matchSummary.missing_png}，缺DWG ${matchSummary.missing_json}，都缺 ${matchSummary.missing_all}`;
  const getDimensionCountFromSummary = (summary?: string | null) => {
    if (!summary) return '-';
    const hit = summary.match(/标注:(\d+)/);
    if (!hit) return '-';
    return hit[1];
  };

  return (
    <div className="min-h-screen bg-gray-50/50 dark:bg-zinc-950 relative overflow-x-hidden pb-12">
      {/* Ambient Orbs */}
      <div className="fixed top-[-10%] left-[-5%] w-[50vw] h-[50vw] bg-primary/5 rounded-full blur-[140px] pointer-events-none -z-10" />
      <div className="fixed bottom-[-10%] right-[-5%] w-[40vw] h-[40vw] bg-blue-500/5 rounded-full blur-[120px] pointer-events-none -z-10" />

      {/* Header */}
      <header className="glass-header z-50">
        <div className="container mx-auto px-6 h-16 flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate('/')} className="hover:bg-gray-100/50 dark:hover:bg-zinc-800/50 rounded-full">
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div className="w-px h-6 bg-gray-200 dark:bg-zinc-800" />
          <div className="flex flex-col justify-center flex-1 min-w-0">
            <h1 className="text-lg font-bold truncate tracking-tight">{project?.name}</h1>
          </div>

          <div className="flex items-center gap-3">
            {category && (
              <Badge variant="outline" className="bg-white/40 dark:bg-black/20 border-transparent shadow-sm hidden sm:inline-flex" style={{ color: category.color }}>
                <span className="w-1.5 h-1.5 rounded-full mr-1.5" style={{ backgroundColor: category.color }} />
                {category.name}
              </Badge>
            )}
            <Badge variant={statusInfo?.variant} className="shadow-sm">
              {project?.status === 'auditing' && <RefreshCw className="h-3 w-3 mr-1.5 animate-spin" />}
              {statusInfo?.label}
            </Badge>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-6 py-8 max-w-[1280px]">
        {/* Modern Stepper */}
        <div className="mb-10 w-full overflow-x-auto pb-4 hide-scrollbar">
          <div className="flex items-center min-w-full justify-between relative px-2">
            {/* Background Line */}
            <div className="absolute top-1/2 left-8 right-8 h-0.5 bg-gray-200 dark:bg-zinc-800 -translate-y-1/2 -z-10" />

            {steps.map((step, index) => {
              const active = isStepActive(index);
              const complete = isStepComplete(index);
              const future = index > currentStep;

              return (
                <div key={step.id} className="flex flex-col items-center relative gap-3 group px-4 z-10 w-1/5">
                  <button
                    onClick={() => setCurrentStep(index)}
                    className={`
                      relative flex items-center justify-center w-12 h-12 rounded-full transition-all duration-500
                      ${future ? 'bg-gray-50 dark:bg-zinc-900 border-2 border-gray-200 dark:border-zinc-800 shadow-sm hover:border-primary/40' : ''}
                      ${!future && !active && !complete ? 'bg-white dark:bg-zinc-800 border-2 border-gray-200 dark:border-zinc-700 shadow-sm hover-lift' : ''}
                      ${active ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/30 ring-4 ring-primary/20 scale-110' : ''}
                      ${complete && !active ? 'bg-success text-success-foreground shadow-lg shadow-success/20 hover:scale-105 transition-transform' : ''}
                    `}
                  >
                    {complete && !active ? <Check className="h-6 w-6" /> : <step.icon className={`h-5 w-5 ${active ? 'animate-pulse' : ''}`} />}
                  </button>
                  <div className="text-center">
                    <div className={`text-sm font-bold transition-colors ${active ? 'text-primary' : complete ? 'text-success' : future ? 'text-muted-foreground' : 'text-foreground'}`}>
                      {step.name}
                    </div>
                    <div className="text-xs text-muted-foreground hidden lg:block mt-1 w-24 mx-auto leading-tight opacity-70">
                      {step.description}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <p className="text-xs text-muted-foreground text-center mt-4">
            步骤支持任意点击回看与回退；已上传图纸与数据不会因回退而删除。
          </p>
        </div>

        {/* Content Area */}
        <div className="transition-all duration-500 animate-in fade-in slide-in-from-bottom-4">

          {/* Step 1: Catalog */}
          {currentStep === 0 && (
            <Card className="glass-card shadow-lg border-white/50 dark:border-white/5 mx-auto max-w-4xl">
              <CardHeader className="text-center pb-2">
                <div className="mx-auto w-12 h-12 bg-primary/10 rounded-full flex items-center justify-center mb-4">
                  <FileText className="h-6 w-6 text-primary" />
                </div>
                <CardTitle className="text-2xl">上传图纸主目录</CardTitle>
                <CardDescription className="text-base text-gray-500 max-w-lg mx-auto">
                  目录是整套图纸的权威依据，确立了系统的识别锚点。请确保长图纸格式为清晰的 PNG/JPG。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6 pt-6 px-10">
                {catalog.length === 0 && !isCatalogEditing ? (
                  <div className="group relative border-2 border-dashed border-primary/30 dark:border-primary/20 rounded-2xl p-16 text-center bg-primary/5 hover:bg-primary/10 transition-colors duration-300">
                    <CloudUpload className="h-16 w-16 mx-auto text-primary/60 mb-6 group-hover:scale-110 transition-transform duration-500" />
                    <h3 className="text-xl font-medium mb-2 text-foreground">拖拽目录图片到此处</h3>
                    <p className="text-muted-foreground mb-8">或点击下方按钮浏览本地文件 (仅支持 PNG/JPG)</p>
                    <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
                      <Label className="cursor-pointer">
                        <Input type="file" accept="image/*" className="hidden" onChange={handleUploadCatalog} disabled={uploading} />
                        <Button asChild size="lg" className="rounded-full shadow-lg shadow-primary/25 hover-lift px-8">
                          <span>{uploading ? <><RefreshCw className="mr-2 h-5 w-5 animate-spin" /> 处理中...</> : '选择目录图片'}</span>
                        </Button>
                      </Label>
                      <Button variant="outline" size="lg" className="rounded-full" onClick={startManualCatalogEdit}>
                        <Pencil className="h-4 w-4 mr-2" />
                        手动编辑目录
                      </Button>
                    </div>
                  </div>
                ) : isCatalogLocked ? (
                  <div className="space-y-6">
                    <div className="flex items-center justify-between gap-3 bg-success/10 border border-success/20 p-4 rounded-xl">
                      <div className="flex items-center gap-3">
                        <CheckCircle className="h-6 w-6 text-success" />
                        <div>
                          <p className="text-success font-semibold text-lg">目录已成功确认并锁定</p>
                          <p className="text-success-foreground/70 text-sm">共识别 {catalog.length} 条条目</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {isCatalogEditing ? (
                          <>
                            <Button variant="outline" onClick={addCatalogDraftRow} disabled={catalogSaving}>
                              <Plus className="h-4 w-4 mr-1.5" />
                              新增行
                            </Button>
                            <Button variant="ghost" onClick={cancelManualCatalogEdit} disabled={catalogSaving}>
                              取消
                            </Button>
                            <Button onClick={saveManualCatalogEdit} disabled={catalogSaving} className="bg-primary hover:bg-primary/90">
                              {catalogSaving ? <RefreshCw className="h-4 w-4 mr-1.5 animate-spin" /> : <Save className="h-4 w-4 mr-1.5" />}
                              保存修改
                            </Button>
                          </>
                        ) : (
                          <Button variant="outline" onClick={startManualCatalogEdit}>
                            <Pencil className="h-4 w-4 mr-1.5" />
                            二次修改目录
                          </Button>
                        )}
                      </div>
                    </div>
                    {catalogEditError && (
                      <p className="text-sm text-red-600 dark:text-red-400">{catalogEditError}</p>
                    )}
                    <Card className="shadow-inner border-gray-100 dark:border-zinc-800">
                      <ScrollArea className="h-[400px]">
                        <table className="w-full text-sm text-left">
                          <thead className="bg-gray-50 dark:bg-zinc-900 sticky top-0 border-b">
                            <tr>
                              <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300 w-20">序号</th>
                              <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300">图号</th>
                              <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300">图名</th>
                              {isCatalogEditing && <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300 w-24 text-center">操作</th>}
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
                            {currentCatalogRows.map((item, index) => (
                              <tr key={item.id || `locked-draft-${index}`} className="hover:bg-gray-50/50 dark:hover:bg-zinc-900/50 transition-colors">
                                <td className="px-6 py-3 font-mono text-muted-foreground">{index + 1}</td>
                                <td className="px-6 py-3">
                                  {isCatalogEditing ? (
                                    <Input
                                      value={item.sheet_no || ''}
                                      onChange={e => updateCatalogDraftField(index, 'sheet_no', e.target.value)}
                                      placeholder="输入图号"
                                      className="h-9"
                                    />
                                  ) : (
                                    <span className="font-medium text-primary">{item.sheet_no || '-'}</span>
                                  )}
                                </td>
                                <td className="px-6 py-3">
                                  {isCatalogEditing ? (
                                    <Input
                                      value={item.sheet_name || ''}
                                      onChange={e => updateCatalogDraftField(index, 'sheet_name', e.target.value)}
                                      placeholder="输入图名"
                                      className="h-9"
                                    />
                                  ) : (
                                    item.sheet_name || '-'
                                  )}
                                </td>
                                {isCatalogEditing && (
                                  <td className="px-6 py-3 text-center">
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      onClick={() => removeCatalogDraftRow(index)}
                                      className="text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30"
                                    >
                                      <Trash2 className="h-4 w-4" />
                                    </Button>
                                  </td>
                                )}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </ScrollArea>
                    </Card>
                  </div>
                ) : (
                  <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="text-lg font-semibold flex items-center">
                          <CheckCircle className="text-success mr-2 h-5 w-5" />
                          {catalog.length > 0 ? '识别成功' : '手动编辑目录'}
                        </h3>
                        <p className="text-muted-foreground text-sm mt-1">
                          {catalog.length > 0
                            ? `系统已提取 ${catalog.length} 条数据，请确认无误后锁定。`
                            : '可手动新增或修改目录条目，保存后再锁定。'}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        {isCatalogEditing ? (
                          <>
                            <Button variant="outline" onClick={addCatalogDraftRow} disabled={catalogSaving}>
                              <Plus className="h-4 w-4 mr-1.5" />
                              新增行
                            </Button>
                            <Button variant="ghost" onClick={cancelManualCatalogEdit} disabled={catalogSaving}>
                              取消
                            </Button>
                            <Button onClick={saveManualCatalogEdit} disabled={catalogSaving} className="bg-primary hover:bg-primary/90">
                              {catalogSaving ? <RefreshCw className="h-4 w-4 mr-1.5 animate-spin" /> : <Save className="h-4 w-4 mr-1.5" />}
                              保存编辑
                            </Button>
                          </>
                        ) : (
                          <>
                            <Button variant="outline" onClick={startManualCatalogEdit}>
                              <Pencil className="h-4 w-4 mr-1.5" />
                              手动编辑目录
                            </Button>
                            <Button onClick={handleLockCatalog} disabled={uploading || catalog.length === 0} size="lg" className="rounded-full shadow-lg shadow-success/20 bg-success hover:bg-success/90 text-white">
                              <Check className="h-5 w-5 mr-2" />
                              锁定并前往下一步
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                    {catalogEditError && (
                      <p className="text-sm text-red-600 dark:text-red-400">{catalogEditError}</p>
                    )}
                    <Card className="shadow-inner border-gray-100 dark:border-zinc-800">
                      <ScrollArea className="h-[400px]">
                        <table className="w-full text-sm text-left">
                          <thead className="bg-gray-50 dark:bg-zinc-900 sticky top-0 border-b">
                            <tr>
                              <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300 w-20">序号</th>
                              <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300">图号</th>
                              <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300">图名</th>
                              {isCatalogEditing && <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300 w-24 text-center">操作</th>}
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
                            {currentCatalogRows.map((item, index) => (
                              <tr key={item.id || `draft-${index}`} className="hover:bg-gray-50/50 dark:hover:bg-zinc-900/50 transition-colors">
                                <td className="px-6 py-3 font-mono text-muted-foreground">{index + 1}</td>
                                <td className="px-6 py-3">
                                  {isCatalogEditing ? (
                                    <Input
                                      value={item.sheet_no || ''}
                                      onChange={e => updateCatalogDraftField(index, 'sheet_no', e.target.value)}
                                      placeholder="输入图号"
                                      className="h-9"
                                    />
                                  ) : (
                                    <span className="font-medium text-primary">{item.sheet_no || '-'}</span>
                                  )}
                                </td>
                                <td className="px-6 py-3">
                                  {isCatalogEditing ? (
                                    <Input
                                      value={item.sheet_name || ''}
                                      onChange={e => updateCatalogDraftField(index, 'sheet_name', e.target.value)}
                                      placeholder="输入图名"
                                      className="h-9"
                                    />
                                  ) : (
                                    item.sheet_name || '-'
                                  )}
                                </td>
                                {isCatalogEditing && (
                                  <td className="px-6 py-3 text-center">
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      onClick={() => removeCatalogDraftRow(index)}
                                      className="text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30"
                                    >
                                      <Trash2 className="h-4 w-4" />
                                    </Button>
                                  </td>
                                )}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </ScrollArea>
                    </Card>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Step 2: Drawings */}
          {currentStep === 1 && (
            <Card className="glass-card shadow-lg border-white/50 dark:border-white/5 mx-auto max-w-4xl">
              <CardHeader className="text-center pb-2">
                <div className="mx-auto w-12 h-12 bg-blue-500/10 rounded-full flex items-center justify-center mb-4">
                  <Image className="h-6 w-6 text-blue-500" />
                </div>
                <CardTitle className="text-2xl">提取全尺寸施工图</CardTitle>
                <CardDescription className="text-base text-gray-500 max-w-lg mx-auto">
                  请上传完整的图纸套册(PDF)。AI 将逐页转化为高清视觉图，并在图面内识别出图名以进行校对。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-8 pt-6 px-10">
                {drawings.length === 0 ? (
                  <div className="group relative border-2 border-dashed border-gray-300 dark:border-zinc-700 rounded-2xl p-12 text-center bg-gray-50/50 dark:bg-zinc-900/50 hover:bg-gray-100 dark:hover:bg-zinc-800 transition-colors duration-300">
                    <FileText className="h-12 w-12 mx-auto text-gray-400 mb-4 group-hover:-translate-y-2 group-hover:text-primary transition-all duration-300" />
                    <p className="text-lg font-medium mb-2">拖拽 PDF 图册至此</p>
                    <p className="text-sm text-gray-500 mb-6">确保文件大小在合理范围内</p>
                    <Label className="cursor-pointer">
                      <Input type="file" accept="application/pdf" className="hidden" onChange={handleUploadDrawings} disabled={uploading} />
                      <Button asChild className="rounded-full">
                        <span>{uploading ? <><RefreshCw className="mr-2 h-4 w-4 animate-spin" /> 疯狂提取中...</> : '选择 PDF'}</span>
                      </Button>
                    </Label>
                  </div>
                ) : (
                  <div className="flex items-center justify-between rounded-xl border border-blue-200/50 bg-blue-50/40 dark:bg-blue-950/20 dark:border-blue-900/50 px-4 py-3">
                    <div className="flex items-center gap-2 text-sm text-blue-800 dark:text-blue-300">
                      <CheckCircle className="h-4 w-4" />
                      已上传 PDF 并提取 {drawings.length} 张图纸
                    </div>
                    <Label className="cursor-pointer">
                      <Input type="file" accept="application/pdf" className="hidden" onChange={handleUploadDrawings} disabled={uploading} />
                      <Button asChild variant="outline" size="sm" className="rounded-full">
                        <span>{uploading ? <><RefreshCw className="mr-1.5 h-4 w-4 animate-spin" /> 重新上传中...</> : '重新上传 PDF'}</span>
                      </Button>
                    </Label>
                  </div>
                )}

                {drawings.length > 0 && (
                  <div className="space-y-4 animate-in fade-in">
                    <div className="flex items-center justify-between">
                      <h3 className="text-lg font-semibold flex items-center gap-2">
                        <CheckCircle className="text-blue-500 h-5 w-5" />
                        已提取 {drawings.length} 张图纸
                      </h3>
                      <Badge variant={unmatchedDrawings.length > 0 ? 'warning' : 'success'}>
                        {unmatchedDrawings.length > 0 ? `待匹配 ${unmatchedDrawings.length} 项` : '全部已匹配'}
                      </Badge>
                    </div>
                    {drawingEditError && (
                      <p className="text-sm text-red-600 dark:text-red-400">{drawingEditError}</p>
                    )}
                    <Card className="shadow-inner border-gray-100 dark:border-zinc-800 overflow-hidden">
                      <ScrollArea className="h-[300px]">
                        <table className="w-full text-sm text-left">
                          <thead className="bg-gray-100/80 dark:bg-zinc-900/80 sticky top-0 backdrop-blur-md">
                            <tr>
                              <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300 w-16 text-center">页码</th>
                              <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300">图内容识别</th>
                              <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300 text-right">匹配状态</th>
                              <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300 text-right w-[260px]">操作</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
                            {drawings.map((item, index) => (
                              <tr key={item.id} className="hover:bg-white dark:hover:bg-zinc-800 transition-colors">
                                <td className="px-6 py-3 text-center font-mono font-medium text-muted-foreground bg-gray-50 dark:bg-zinc-900/50">
                                  {(item.page_index ?? index) + 1}
                                </td>
                                <td className="px-6 py-3">
                                  {editingDrawingId === item.id ? (
                                    <div className="space-y-2">
                                      <div className="flex flex-col">
                                        <span className="font-semibold text-primary">{item.sheet_no || '未识别'}</span>
                                        <span className="text-muted-foreground">{item.sheet_name || '-'}</span>
                                      </div>
                                      <Select
                                        value={drawingDraft.catalog_id || undefined}
                                        onValueChange={value => setDrawingDraft({ catalog_id: value })}
                                      >
                                        <SelectTrigger className="h-9 w-full">
                                          <SelectValue placeholder="选择要匹配的目录项" />
                                        </SelectTrigger>
                                        <SelectContent>
                                          {catalog.map((cat, idx) => (
                                            <SelectItem key={cat.id} value={cat.id}>
                                              {`${idx + 1}. ${cat.sheet_no || '未编号'} - ${cat.sheet_name || '未命名'}`}
                                            </SelectItem>
                                          ))}
                                        </SelectContent>
                                      </Select>
                                    </div>
                                  ) : (
                                    <div className="flex flex-col">
                                      <span className="font-semibold text-primary">{item.sheet_no || '未识别'}</span>
                                      <span className="text-muted-foreground">{item.sheet_name || '-'}</span>
                                    </div>
                                  )}
                                </td>
                                <td className="px-6 py-3 text-right">
                                  <Badge variant={item.status === 'matched' ? 'success' : 'warning'} className="shadow-sm">
                                    {item.status === 'matched' ? '已匹配' : '待匹配'}
                                  </Badge>
                                </td>
                                <td className="px-6 py-3 text-right">
                                  {editingDrawingId === item.id ? (
                                    <div className="flex items-center justify-end gap-2">
                                      <Button variant="ghost" size="sm" onClick={cancelEditDrawing} disabled={drawingSaveLoading}>
                                        取消
                                      </Button>
                                      <Button size="sm" onClick={() => saveEditDrawing(item.id)} disabled={drawingSaveLoading || !drawingDraft.catalog_id}>
                                        {drawingSaveLoading ? <RefreshCw className="h-4 w-4 animate-spin" /> : '保存'}
                                      </Button>
                                    </div>
                                  ) : item.status !== 'matched' ? (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      onClick={() => startEditDrawing(item)}
                                    >
                                      手动修改
                                    </Button>
                                  ) : (
                                    <span className="text-xs text-muted-foreground">-</span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </ScrollArea>
                    </Card>
                    <div className="flex justify-end pt-4">
                      <Button onClick={() => setCurrentStep(2)} size="lg" className="rounded-full shadow-lg shadow-primary/20 hover-lift">
                        确认无误，前往下一步
                        <ArrowRight className="ml-2 w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Step 3: DWG Data */}
          {currentStep === 2 && (
            <Card className="glass-card shadow-lg border-white/50 dark:border-white/5 mx-auto max-w-4xl">
              <CardHeader className="text-center pb-2">
                <div className="mx-auto w-12 h-12 bg-amber-500/10 rounded-full flex items-center justify-center mb-4">
                  <Database className="h-6 w-6 text-amber-500" />
                </div>
                <CardTitle className="text-2xl">导入 AutoCAD 底层数据</CardTitle>
                <CardDescription className="text-base text-gray-500 max-w-lg mx-auto">
                  直接提取原文件的精准工程尺寸与标注参数，用于辅助 AI 做全息数字比对。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-8 pt-6 px-10">

                <div className="bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-950/30 dark:to-orange-950/30 border border-amber-200/50 dark:border-amber-800/50 rounded-xl p-4 flex items-start gap-3">
                  <AlertCircle className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
                  <p className="text-amber-800 dark:text-amber-300 text-sm leading-relaxed">
                    本步骤由于需要调用 COM 接口，建议必须在已正确安装且配置了 AutoCAD 的本地 Windows 环境下运行 CAD-Extractor 工具来转换。平台仅接收上传 `.dwg` 提取后的关联文件(支持多选)。
                  </p>
                </div>

                <div className="group relative border-2 border-dashed border-gray-300 dark:border-zinc-700 rounded-2xl p-12 text-center bg-gray-50/50 dark:bg-zinc-900/50 hover:bg-gray-100 dark:hover:bg-zinc-800 transition-colors duration-300">
                  <FileCode2 className="h-12 w-12 mx-auto text-gray-400 mb-4 group-hover:-translate-y-2 group-hover:text-amber-500 transition-all duration-300" />
                  <p className="text-lg font-medium mb-2">批量拖入对应 DWG 数据</p>
                  <Label className="cursor-pointer">
                    <Input type="file" accept=".dwg" multiple className="hidden" onChange={handleUploadDwg} disabled={uploading} />
                    <Button asChild variant="secondary" className="mt-4 rounded-full shadow-sm hover-lift">
                      <span>{uploading ? <><RefreshCw className="mr-2 h-4 w-4 animate-spin" /> 读取中...</> : '选择文件库...'}</span>
                    </Button>
                  </Label>
                </div>

                {jsonData.length > 0 && (
                  <div className="space-y-4 animate-in fade-in">
                    <h3 className="text-lg font-semibold flex items-center gap-2">
                      <CheckCircle className="text-amber-500 h-5 w-5" />
                      数据就绪 ({jsonData.length} 份)
                    </h3>
                    <Card className="shadow-inner border-gray-100 dark:border-zinc-800">
                      <ScrollArea className="h-[250px]">
                        <table className="w-full text-sm text-left">
                          <thead className="bg-gray-100/80 dark:bg-zinc-900/80 sticky top-0 backdrop-blur-md">
                            <tr>
                              <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300">图号引用</th>
                              <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300">提取摘要序列</th>
                              <th className="px-6 py-3 font-semibold text-gray-700 dark:text-gray-300 text-right">状态</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
                            {jsonData.map(item => (
                              <tr key={item.id} className="hover:bg-white dark:hover:bg-zinc-800 transition-colors">
                                <td className="px-6 py-3 font-semibold text-amber-600 dark:text-amber-500">{item.sheet_no || '-'}</td>
                                <td className="px-6 py-3 text-muted-foreground font-mono text-xs max-w-xs truncate">{item.summary || '解析成功：包含块参照与直线维度...'}</td>
                                <td className="px-6 py-3 text-right">
                                  <Badge variant={item.status === 'matched' ? 'success' : 'secondary'} className="shadow-sm">
                                    {item.status === 'matched' ? '已匹配' : '解析成功'}
                                  </Badge>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </ScrollArea>
                    </Card>
                    <div className="flex justify-end pt-4">
                      <Button onClick={() => setCurrentStep(3)} size="lg" className="rounded-full shadow-lg shadow-amber-500/20 bg-amber-500 hover:bg-amber-600 hover-lift text-white">
                        合并验证匹配链路
                        <ArrowRight className="ml-2 w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Step 4: Verification & Match */}
          {currentStep === 3 && (
            <Card className="glass-card shadow-lg border-white/50 dark:border-white/5 mx-auto max-w-5xl">
              <CardHeader className="text-center pb-6">
                <div className="mx-auto w-12 h-12 bg-indigo-500/10 rounded-full flex items-center justify-center mb-4">
                  <FileSearch className="h-6 w-6 text-indigo-500" />
                </div>
                <CardTitle className="text-2xl">三线匹配确认</CardTitle>
                <CardDescription className="text-base text-gray-500 max-w-2xl mx-auto">
                  以锁定目录为基准，逐条核验 PNG 与 JSON 是否一对一齐备。缺失项可直接跳转对应步骤修复。
                </CardDescription>
              </CardHeader>
              <CardContent className="px-8 pb-8">
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
                  <Card className="shadow-sm border-gray-200 dark:border-zinc-800">
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">总条目</p>
                      <p className="text-2xl font-bold">{matchSummary.total}</p>
                    </CardContent>
                  </Card>
                  <Card className="shadow-sm border-gray-200 dark:border-zinc-800">
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">可审核</p>
                      <p className="text-2xl font-bold text-green-600">{matchSummary.ready}</p>
                    </CardContent>
                  </Card>
                  <Card className="shadow-sm border-gray-200 dark:border-zinc-800">
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">缺 PNG</p>
                      <p className="text-2xl font-bold text-amber-600">{matchSummary.missing_png}</p>
                    </CardContent>
                  </Card>
                  <Card className="shadow-sm border-gray-200 dark:border-zinc-800">
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">缺 DWG</p>
                      <p className="text-2xl font-bold text-orange-600">{matchSummary.missing_json}</p>
                    </CardContent>
                  </Card>
                  <Card className="shadow-sm border-gray-200 dark:border-zinc-800">
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">都缺</p>
                      <p className="text-2xl font-bold text-red-600">{matchSummary.missing_all}</p>
                    </CardContent>
                  </Card>
                </div>

                <div className="flex items-center justify-between mb-4 gap-3">
                  <Select value={matchFilter} onValueChange={value => setMatchFilter(value as MatchFilter)}>
                    <SelectTrigger className="w-[220px]">
                      <SelectValue placeholder="筛选状态" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">全部</SelectItem>
                      <SelectItem value="missing">仅缺失项</SelectItem>
                      <SelectItem value="ready">仅可审核</SelectItem>
                      <SelectItem value="missing_png">缺 PNG</SelectItem>
                      <SelectItem value="missing_json">缺 DWG</SelectItem>
                      <SelectItem value="missing_all">都缺</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button variant="outline" onClick={loadData} disabled={uploading}>
                    <RefreshCw className="mr-2 h-4 w-4" />
                    刷新三线状态
                  </Button>
                </div>

                <Card className="shadow-sm border-gray-200 dark:border-zinc-800 overflow-hidden mb-8">
                  <ScrollArea className="h-[450px]">
                    <table className="w-full text-sm text-left">
                      <thead className="bg-indigo-50 dark:bg-zinc-900 border-b border-indigo-100 dark:border-zinc-800 sticky top-0 backdrop-blur-md z-10">
                        <tr>
                          <th className="px-6 py-4 font-bold text-gray-900 dark:text-gray-100">目录锚点</th>
                          <th className="px-6 py-4 font-bold text-gray-900 dark:text-gray-100 text-center">PNG 预览</th>
                          <th className="px-6 py-4 font-bold text-gray-900 dark:text-gray-100 text-center">DWG数据摘要</th>
                          <th className="px-6 py-4 font-bold text-gray-900 dark:text-gray-100 text-center">状态</th>
                          <th className="px-6 py-4 font-bold text-gray-900 dark:text-gray-100 text-right">修复入口</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
                        {filteredMatchItems.length === 0 && (
                          <tr>
                            <td colSpan={5} className="px-6 py-10 text-center text-muted-foreground">
                              当前筛选条件下暂无数据
                            </td>
                          </tr>
                        )}
                        {filteredMatchItems.map(item => {
                          const statusBadge = item.status === 'ready'
                            ? { text: '可审核', variant: 'success' as const }
                            : item.status === 'missing_png'
                              ? { text: '缺图纸', variant: 'warning' as const }
                              : item.status === 'missing_json'
                                ? { text: '缺DWG', variant: 'warning' as const }
                                : { text: '都缺', variant: 'destructive' as const };
                          return (
                            <tr key={item.catalog_id} className="hover:bg-gray-50 dark:hover:bg-zinc-900/50 transition-colors">
                              <td className="px-6 py-4">
                                <div className="flex flex-col">
                                  <span className="font-semibold text-primary">{item.sheet_no || '-'}</span>
                                  <span className="text-muted-foreground truncate max-w-[280px]">{item.sheet_name || '-'}</span>
                                </div>
                              </td>
                              <td className="px-6 py-4 text-center">
                                {item.drawing?.id && item.drawing.png_path && id ? (
                                  <img
                                    src={api.getDrawingImageUrl(id, item.drawing.id, project?.cache_version)}
                                    alt={item.sheet_no || 'drawing'}
                                    className="w-[50px] h-[50px] object-cover rounded-md border border-gray-200 dark:border-zinc-700 inline-block"
                                  />
                                ) : (
                                  <span className="text-xs text-muted-foreground">未上传</span>
                                )}
                              </td>
                              <td className="px-6 py-4 text-center">
                                {item.json?.id && item.json.json_path ? (
                                  <div className="text-xs leading-relaxed">
                                    <div>标注数: {getDimensionCountFromSummary(item.json.summary)}</div>
                                    <div className="text-muted-foreground">v{item.json.data_version || 1}</div>
                                  </div>
                                ) : (
                                  <span className="text-xs text-muted-foreground">未生成</span>
                                )}
                              </td>
                              <td className="px-6 py-4 text-center">
                                <Badge variant={statusBadge.variant} className="shadow-sm py-1">
                                  {statusBadge.text}
                                </Badge>
                              </td>
                              <td className="px-6 py-4 text-right">
                                {item.status === 'ready' ? (
                                  <span className="text-xs text-muted-foreground">-</span>
                                ) : item.status === 'missing_png' ? (
                                  <Button size="sm" variant="outline" onClick={() => setCurrentStep(1)}>
                                    去补 PNG
                                  </Button>
                                ) : item.status === 'missing_json' ? (
                                  <Button size="sm" variant="outline" onClick={() => setCurrentStep(2)}>
                                    去补 DWG
                                  </Button>
                                ) : (
                                  <div className="flex justify-end gap-2">
                                    <Button size="sm" variant="outline" onClick={() => setCurrentStep(1)}>
                                      补 PNG
                                    </Button>
                                    <Button size="sm" variant="outline" onClick={() => setCurrentStep(2)}>
                                      补 DWG
                                    </Button>
                                  </div>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </ScrollArea>
                </Card>

                <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="inline-flex w-full sm:w-auto">
                          <Button
                            onClick={handleStartAudit}
                            disabled={uploading || !canStartAudit}
                            size="lg"
                            className="rounded-full w-full sm:w-auto shadow-xl shadow-indigo-500/20 bg-indigo-600 hover:bg-indigo-700 text-white hover:scale-105 transition-all disabled:opacity-50"
                          >
                            {uploading ? (
                              <><RefreshCw className="mr-2 h-5 w-5 animate-spin" /> 执行审核中...</>
                            ) : (
                              <><Play className="mr-2 h-5 w-5 fill-current" /> 开始审核</>
                            )}
                          </Button>
                        </span>
                      </TooltipTrigger>
                      {!canStartAudit && (
                        <TooltipContent sideOffset={8}>
                          {blockedReason}
                        </TooltipContent>
                      )}
                    </Tooltip>
                  </TooltipProvider>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Step 5: Audit Dashboard */}
          {currentStep === 4 && (
            <div className="space-y-8 animate-in fade-in zoom-in-95 duration-500 max-w-6xl mx-auto">
              {auditStatus?.status === 'auditing' ? (
                <Card className="glass-card shadow-lg border-white/50 p-16 text-center">
                  <div className="relative w-32 h-32 mx-auto mb-8">
                    <div className="absolute inset-0 bg-primary/20 rounded-full animate-ping" />
                    <div className="absolute inset-0 bg-gradient-to-tr from-primary to-blue-400 rounded-full p-1 opacity-20 animate-spin" />
                    <div className="relative w-full h-full bg-white dark:bg-zinc-900 rounded-full shadow-inner flex items-center justify-center border border-gray-100 dark:border-zinc-800">
                      <RefreshCw className="h-10 w-10 text-primary animate-spin" />
                    </div>
                  </div>
                  <h3 className="text-2xl font-bold mb-3">AI 内核正在疯狂扫描核对</h3>
                  <p className="text-muted-foreground max-w-md mx-auto mb-6">
                    正在执行：引线指向核查(包含平立面大样匹配) ➔ 标注尺寸绝对距离解析 ➔ 涂装材料冲突比对...
                  </p>
                  <Progress value={65} className="w-[300px] mx-auto h-2 bg-primary/10" />
                </Card>
              ) : auditStatus?.status === 'done' ? (
                <>
                  <div className="flex flex-col sm:flex-row items-center justify-between mb-2 gap-4">
                    <div>
                      <h2 className="text-3xl font-bold tracking-tight mb-2">智能深度核对报告</h2>
                      <p className="text-muted-foreground flex items-center">
                        <CheckCircle className="h-4 w-4 text-success mr-2" />
                        分析已完成，已高亮所有不匹配的隐患红线。
                      </p>
                    </div>
                    <div className="flex gap-3">
                      <Button variant="outline" onClick={handleDownloadExcel} className="rounded-full shadow-sm hover-lift bg-white/50 dark:bg-zinc-900/50 backdrop-blur-md">
                        <Download className="mr-2 h-4 w-4" /> Excel
                      </Button>
                      <Button onClick={handleDownloadPdf} className="rounded-full shadow-lg hover-lift shadow-primary/20">
                        <Download className="mr-2 h-4 w-4" /> 导出可视化 PDF
                      </Button>
                    </div>
                  </div>

                  {/* Dashboard Cards */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6">
                    <Card className="glass-card border-none bg-gradient-to-br from-white to-gray-50 shadow-md">
                      <CardContent className="p-6">
                        <p className="text-sm font-medium text-gray-500 mb-1">总计发现隐患</p>
                        <div className="flex items-baseline gap-2">
                          <p className="text-4xl font-extrabold text-gray-900 tracking-tighter">{auditStatus.total_issues}</p>
                          <span className="text-sm text-red-500 font-medium">+100%</span>
                        </div>
                      </CardContent>
                    </Card>
                    <Card className="glass-card border-none bg-gradient-to-br from-red-50 to-white shadow-md">
                      <CardContent className="p-6">
                        <p className="text-sm font-medium text-red-600/80 mb-1 flex items-center"><X className="h-3 w-3 mr-1" /> 索引孤岛/断链</p>
                        <p className="text-4xl font-extrabold text-red-600 tracking-tighter">{auditResults.filter(r => r.type === 'index').length}</p>
                      </CardContent>
                    </Card>
                    <Card className="glass-card border-none bg-gradient-to-br from-amber-50 to-white shadow-md">
                      <CardContent className="p-6">
                        <p className="text-sm font-medium text-amber-600/80 mb-1 flex items-center"><AlertCircle className="h-3 w-3 mr-1" /> 尺寸错位</p>
                        <p className="text-4xl font-extrabold text-amber-600 tracking-tighter">{auditResults.filter(r => r.type === 'dimension').length}</p>
                      </CardContent>
                    </Card>
                    <Card className="glass-card border-none bg-gradient-to-br from-orange-50 to-white shadow-md">
                      <CardContent className="p-6">
                        <p className="text-sm font-medium text-orange-600/80 mb-1 flex items-center"><Database className="h-3 w-3 mr-1" /> 材料表矛盾</p>
                        <p className="text-4xl font-extrabold text-orange-600 tracking-tighter">{auditResults.filter(r => r.type === 'material').length}</p>
                      </CardContent>
                    </Card>
                  </div>

                  {/* Details List */}
                  <Card className="glass-card mt-8 shadow-xl">
                    <Tabs defaultValue="all" className="w-full">
                      <div className="px-6 pt-6 pb-2 border-b border-gray-100 dark:border-zinc-800">
                        <TabsList className="bg-gray-100/50 dark:bg-zinc-900/50 p-1">
                          <TabsTrigger value="all" className="rounded-md">全部隐患</TabsTrigger>
                          <TabsTrigger value="index" className="rounded-md text-red-600 data-[state=active]:bg-red-100 data-[state=active]:text-red-700">索引断链</TabsTrigger>
                          <TabsTrigger value="dimension" className="rounded-md text-amber-600 data-[state=active]:bg-amber-100 data-[state=active]:text-amber-700">尺寸比对</TabsTrigger>
                        </TabsList>
                      </div>
                      <TabsContent value="all" className="m-0">
                        <ScrollArea className="h-[500px] w-full bg-gray-50/30 dark:bg-zinc-950/30">
                          {auditResults.length > 0 ? (
                            <div className="p-6 space-y-4">
                              {auditResults.map(result => (
                                <div key={result.id} className="group flex flex-col md:flex-row gap-4 p-5 bg-white dark:bg-zinc-900 border border-gray-100 dark:border-zinc-800 rounded-xl shadow-[0_2px_10px_-3px_rgba(0,0,0,0.05)] hover:shadow-[0_8px_30px_-4px_rgba(0,0,0,0.1)] transition-all duration-300">
                                  <div className="shrink-0 pt-0.5">
                                    <Badge variant={result.severity === 'error' ? 'destructive' : 'warning'} className="px-3 py-1 text-xs tracking-wide">
                                      {result.type === 'index' ? '索引断链' : result.type === 'dimension' ? '尺寸矛盾' : '材料问题'}
                                    </Badge>
                                  </div>
                                  <div className="flex-1 space-y-2">
                                    <div className="flex items-center gap-2 text-sm font-mono bg-gray-50 dark:bg-zinc-950 px-3 py-1.5 rounded-md text-primary w-fit border border-gray-200 dark:border-zinc-800">
                                      <span>{result.sheet_no_a}</span>
                                      <ArrowRight className="h-3 w-3 text-muted-foreground" />
                                      <span>{result.sheet_no_b || '未知/丢失目标'}</span>
                                    </div>
                                    <p className="text-[15px] leading-relaxed text-gray-700 dark:text-gray-300">
                                      {result.description}
                                    </p>
                                  </div>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="p-20 text-center flex flex-col items-center">
                              <CheckCircle className="h-16 w-16 text-success/50 mb-4" />
                              <p className="text-xl font-medium text-success">完美状态</p>
                              <p className="text-muted-foreground mt-2">没有任何发现问题，您的工程图纸质量堪称卓越。</p>
                            </div>
                          )}
                        </ScrollArea>
                      </TabsContent>
                      <TabsContent value="index" className="m-0 text-center py-20 bg-gray-50/50">
                        <p className="text-muted-foreground">已过滤显示：索引类</p>
                      </TabsContent>
                      <TabsContent value="dimension" className="m-0 text-center py-20 bg-gray-50/50">
                        <p className="text-muted-foreground">已过滤显示：尺寸比对类</p>
                      </TabsContent>
                    </Tabs>
                  </Card>
                </>
              ) : (
                <div className="text-center py-20">
                  <LayoutDashboard className="h-16 w-16 mx-auto text-gray-300 mb-6" />
                  <p className="text-xl text-gray-400">请逐步解锁前面的关键结构，方可查看全息智能报告</p>
                </div>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
