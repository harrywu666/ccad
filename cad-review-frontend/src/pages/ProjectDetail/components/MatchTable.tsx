import { Eye, MoreVertical, Pencil, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { useEffect, useMemo, useState } from 'react';
import type { ThreeLineItem, MatchFilter, Drawing } from '@/types';
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

interface MatchTableProps {
    items: ThreeLineItem[];
    filter: MatchFilter;
    onFilterChange: (f: MatchFilter) => void;
    onPreviewDrawing: (item: ThreeLineItem) => void;
    hasUploadedDrawings: boolean;
    unmatchedDrawings: Drawing[];
    onManualCatalogMatch: (payload: { catalogId: string; drawingId: string; sheetNo?: string | null; sheetName?: string | null }) => Promise<void>;
    onDeleteDrawing: (drawingId: string) => Promise<void>;
    onDeleteJson: (jsonId: string) => Promise<void>;
    onBatchDeleteDrawings: (drawingIds: string[]) => Promise<void>;
    onBatchDeleteJson: (jsonIds: string[]) => Promise<void>;
    stats: {
        total: number;
        ready: number;
        missing: number;
        missing_png: number;
        missing_json: number;
    };
}

type DeleteConfirmAction =
    | { type: 'single_pdf'; drawingId: string; label: string }
    | { type: 'single_dwg'; jsonId: string; label: string }
    | { type: 'batch_pdf'; drawingIds: string[]; count: number }
    | { type: 'batch_dwg'; jsonIds: string[]; count: number };

export default function MatchTable({
    items,
    filter,
    onFilterChange,
    onPreviewDrawing,
    hasUploadedDrawings,
    unmatchedDrawings,
    onManualCatalogMatch,
    onDeleteDrawing,
    onDeleteJson,
    onBatchDeleteDrawings,
    onBatchDeleteJson,
    stats
}: MatchTableProps) {
    const [editingCatalogId, setEditingCatalogId] = useState<string | null>(null);
    const [selectedDrawingId, setSelectedDrawingId] = useState<string>('');
    const [savingCatalogId, setSavingCatalogId] = useState<string | null>(null);
    const [isBatchMode, setIsBatchMode] = useState(false);
    const [selectedCatalogIds, setSelectedCatalogIds] = useState<Set<string>>(new Set());
    const [deletingKey, setDeletingKey] = useState<string | null>(null);
    const [batchDeletingType, setBatchDeletingType] = useState<'pdf' | 'dwg' | null>(null);
    const [deleteConfirmAction, setDeleteConfirmAction] = useState<DeleteConfirmAction | null>(null);

    const drawingOptions = useMemo(() => unmatchedDrawings.map((drawing, idx) => ({
        value: drawing.id,
        label: `${idx + 1}. ${drawing.sheet_no || '未识别图号'} - ${drawing.sheet_name || '未识别图名'}${drawing.page_index !== null && drawing.page_index !== undefined ? ` (第${drawing.page_index + 1}页)` : ''}`
    })), [unmatchedDrawings]);

    useEffect(() => {
        setSelectedCatalogIds(prev => {
            const valid = new Set(items.map(i => i.catalog_id));
            return new Set([...prev].filter(id => valid.has(id)));
        });
    }, [items]);

    useEffect(() => {
        if (!isBatchMode && selectedCatalogIds.size > 0) {
            setSelectedCatalogIds(new Set());
        }
    }, [isBatchMode, selectedCatalogIds]);

    const selectedItems = useMemo(
        () => items.filter(item => selectedCatalogIds.has(item.catalog_id)),
        [items, selectedCatalogIds]
    );
    const selectedDrawingIds = useMemo(
        () => Array.from(new Set(selectedItems.map(item => item.drawing?.id).filter(Boolean) as string[])),
        [selectedItems]
    );
    const selectedJsonIds = useMemo(
        () => Array.from(new Set(selectedItems.map(item => item.json?.id).filter(Boolean) as string[])),
        [selectedItems]
    );
    const allChecked = items.length > 0 && selectedCatalogIds.size === items.length;

    const startEditCatalogMatch = (catalogId: string) => {
        setEditingCatalogId(catalogId);
        setSelectedDrawingId('');
    };

    const cancelEditCatalogMatch = () => {
        setEditingCatalogId(null);
        setSelectedDrawingId('');
        setSavingCatalogId(null);
    };

    const saveCatalogMatch = async (item: ThreeLineItem) => {
        if (!selectedDrawingId) return;
        try {
            setSavingCatalogId(item.catalog_id);
            await onManualCatalogMatch({
                catalogId: item.catalog_id,
                drawingId: selectedDrawingId,
                sheetNo: item.sheet_no,
                sheetName: item.sheet_name,
            });
            cancelEditCatalogMatch();
        } catch {
            setSavingCatalogId(null);
        }
    };

    const toggleSelectRow = (catalogId: string, checked: boolean) => {
        setSelectedCatalogIds(prev => {
            const next = new Set(prev);
            if (checked) next.add(catalogId);
            else next.delete(catalogId);
            return next;
        });
    };

    const toggleSelectAll = (checked: boolean) => {
        if (checked) {
            setSelectedCatalogIds(new Set(items.map(item => item.catalog_id)));
        } else {
            setSelectedCatalogIds(new Set());
        }
    };

    const handleDeleteDrawing = (drawingId: string, label: string) => {
        setDeleteConfirmAction({ type: 'single_pdf', drawingId, label });
    };

    const handleDeleteJson = (jsonId: string, label: string) => {
        setDeleteConfirmAction({ type: 'single_dwg', jsonId, label });
    };

    const handleBatchDeleteDrawings = () => {
        if (!selectedDrawingIds.length) return;
        setDeleteConfirmAction({
            type: 'batch_pdf',
            drawingIds: selectedDrawingIds,
            count: selectedDrawingIds.length,
        });
    };

    const handleBatchDeleteJson = () => {
        if (!selectedJsonIds.length) return;
        setDeleteConfirmAction({
            type: 'batch_dwg',
            jsonIds: selectedJsonIds,
            count: selectedJsonIds.length,
        });
    };

    const handleConfirmDelete = async () => {
        if (!deleteConfirmAction) return;

        if (deleteConfirmAction.type === 'single_pdf') {
            const { drawingId } = deleteConfirmAction;
            try {
                setDeletingKey(`pdf-${drawingId}`);
                await onDeleteDrawing(drawingId);
                setDeleteConfirmAction(null);
            } finally {
                setDeletingKey(null);
            }
            return;
        }

        if (deleteConfirmAction.type === 'single_dwg') {
            const { jsonId } = deleteConfirmAction;
            try {
                setDeletingKey(`dwg-${jsonId}`);
                await onDeleteJson(jsonId);
                setDeleteConfirmAction(null);
            } finally {
                setDeletingKey(null);
            }
            return;
        }

        if (deleteConfirmAction.type === 'batch_pdf') {
            const { drawingIds } = deleteConfirmAction;
            try {
                setBatchDeletingType('pdf');
                await onBatchDeleteDrawings(drawingIds);
                setSelectedCatalogIds(new Set());
                setIsBatchMode(false);
                setDeleteConfirmAction(null);
            } finally {
                setBatchDeletingType(null);
            }
            return;
        }

        const { jsonIds } = deleteConfirmAction;
        try {
            setBatchDeletingType('dwg');
            await onBatchDeleteJson(jsonIds);
            setSelectedCatalogIds(new Set());
            setIsBatchMode(false);
            setDeleteConfirmAction(null);
        } finally {
            setBatchDeletingType(null);
        }
    };

    const exitBatchMode = () => {
        setIsBatchMode(false);
        setSelectedCatalogIds(new Set());
    };

    const handleRowClick = (event: React.MouseEvent<HTMLTableRowElement>, item: ThreeLineItem) => {
        if (!item.drawing?.png_path) return;
        const target = event.target as HTMLElement;
        if (
            target.closest(
                'button, input, [role="button"], [role="menuitem"], [data-slot="button"], [data-slot="input"], [data-slot="select-trigger"], [data-radix-collection-item]'
            )
        ) {
            return;
        }
        onPreviewDrawing(item);
    };

    const deleteDialogCopy = useMemo(() => {
        if (!deleteConfirmAction) return null;
        if (deleteConfirmAction.type === 'single_pdf') {
            return {
                title: '删除PDF图纸',
                description: '删除后不可恢复，匹配关系可能受影响。',
                targetLabel: deleteConfirmAction.label,
                confirmText: '确认删除',
                deletingText: '删除中...',
                isDeleting: deletingKey === `pdf-${deleteConfirmAction.drawingId}`,
            };
        }
        if (deleteConfirmAction.type === 'single_dwg') {
            return {
                title: '删除DWG数据',
                description: '删除后不可恢复，审核数据将不可用。',
                targetLabel: deleteConfirmAction.label,
                confirmText: '确认删除',
                deletingText: '删除中...',
                isDeleting: deletingKey === `dwg-${deleteConfirmAction.jsonId}`,
            };
        }
        if (deleteConfirmAction.type === 'batch_pdf') {
            return {
                title: '批量删除PDF图纸',
                description: '删除后不可恢复，请确认本次批量删除范围。',
                targetLabel: `${deleteConfirmAction.count} 条 PDF 图纸`,
                confirmText: '确认批量删除',
                deletingText: '删除中...',
                isDeleting: batchDeletingType === 'pdf',
            };
        }
        return {
            title: '批量删除DWG数据',
            description: '删除后不可恢复，请确认本次批量删除范围。',
            targetLabel: `${deleteConfirmAction.count} 条 DWG 数据`,
            confirmText: '确认批量删除',
            deletingText: '删除中...',
            isDeleting: batchDeletingType === 'dwg',
        };
    }, [deleteConfirmAction, deletingKey, batchDeletingType]);

    return (
        <div className="w-full flex flex-col gap-6 bg-secondary/30 p-5 border border-border">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <h2 className="text-[18px] font-semibold font-sans text-foreground mb-1">匹配明细 (总计 {stats.total} 条)</h2>
                    <p className="text-[13px] text-muted-foreground font-sans flex gap-4">
                        <span><span className="text-success font-medium">齐备:</span> {stats.ready}</span>
                        <span><span className="text-primary font-medium">缺项:</span> {stats.missing}</span>
                    </p>
                </div>

                <div className="flex items-center gap-2">
                    {!isBatchMode ? (
                        <Button
                            variant="outline"
                            size="sm"
                            className="rounded-none h-9 px-3 text-[13px] shadow-none hover:shadow-none"
                            onClick={() => setIsBatchMode(true)}
                        >
                            批量管理
                        </Button>
                    ) : selectedCatalogIds.size > 0 ? (
                        <>
                            <Button
                                variant="destructive"
                                size="sm"
                                className="rounded-none h-9 px-3 text-[13px] shadow-none hover:shadow-none"
                                disabled={!selectedDrawingIds.length || batchDeletingType !== null}
                                onClick={handleBatchDeleteDrawings}
                            >
                                <Trash2 className="w-4 h-4 mr-1" />
                                {batchDeletingType === 'pdf' ? '删除中...' : `删PDF (${selectedDrawingIds.length})`}
                            </Button>
                            <Button
                                variant="destructive"
                                size="sm"
                                className="rounded-none h-9 px-3 text-[13px] shadow-none hover:shadow-none"
                                disabled={!selectedJsonIds.length || batchDeletingType !== null}
                                onClick={handleBatchDeleteJson}
                            >
                                <Trash2 className="w-4 h-4 mr-1" />
                                {batchDeletingType === 'dwg' ? '删除中...' : `删DWG (${selectedJsonIds.length})`}
                            </Button>
                        </>
                    ) : (
                        <Button
                            variant="outline"
                            size="sm"
                            className="rounded-none h-9 px-3 text-[13px] shadow-none hover:shadow-none"
                            onClick={exitBatchMode}
                        >
                            退出
                        </Button>
                    )}
                    <Select value={filter} onValueChange={(v) => onFilterChange(v as MatchFilter)}>
                        <SelectTrigger className="w-[140px] rounded-none bg-white border-border shadow-none h-9 text-[13px]">
                            <SelectValue placeholder="显示所有" />
                        </SelectTrigger>
                        <SelectContent className="rounded-none border-border shadow-md">
                            <SelectItem value="all" className="text-[13px] rounded-none">所有数据 ({stats.total})</SelectItem>
                            <SelectItem value="ready" className="text-[13px] rounded-none">仅显示齐备 ({stats.ready})</SelectItem>
                            <SelectItem value="missing" className="text-[13px] rounded-none">所有缺项 ({stats.missing})</SelectItem>
                            <SelectItem value="missing_png" className="text-[13px] rounded-none">缺图纸 ({stats.missing_png})</SelectItem>
                            <SelectItem value="missing_json" className="text-[13px] rounded-none">缺数据 ({stats.missing_json})</SelectItem>
                        </SelectContent>
                    </Select>
                </div>
            </div>

            <Card className="border-border shadow-none rounded-none flex-1 overflow-hidden flex flex-col min-h-[400px]">
                <ScrollArea className="flex-1">
                    <table className="w-full text-[13px] font-sans text-left">
                        <thead className="bg-zinc-100 sticky top-0 border-b border-border z-10">
                            <tr>
                                {isBatchMode && (
                                    <th className="px-4 py-4 font-semibold text-muted-foreground w-12 align-middle text-center">
                                        <input
                                            type="checkbox"
                                            className="h-4 w-4 align-middle accent-primary"
                                            checked={allChecked}
                                            onChange={(e) => toggleSelectAll(e.target.checked)}
                                        />
                                    </th>
                                )}
                                <th className="px-6 py-4 font-semibold text-muted-foreground w-20 align-middle">序号</th>
                                <th className="px-6 py-4 font-semibold text-muted-foreground align-middle">图号</th>
                                <th className="px-6 py-4 font-semibold text-muted-foreground align-middle">目录图名</th>
                                <th className="px-6 py-4 font-semibold text-muted-foreground w-52 align-middle text-center">目录匹配</th>
                                <th className="px-6 py-4 font-semibold text-muted-foreground w-32 align-middle text-center">图纸 (PDF)</th>
                                <th className="px-6 py-4 font-semibold text-muted-foreground w-32 align-middle text-center">数据 (DWG)</th>
                                <th className="px-6 py-4 font-semibold text-muted-foreground w-28 align-middle text-center">操作</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border bg-white">
                            {items.length === 0 ? (
                                <tr>
                                    <td colSpan={isBatchMode ? 8 : 7} className="px-6 py-12 text-center text-muted-foreground">
                                        暂无匹配数据，请先锁定目录。
                                    </td>
                                </tr>
                            ) : (
                                items.map((item, index) => (
                                    <tr
                                        key={item.catalog_id || index}
                                        onClick={(event) => handleRowClick(event, item)}
                                        className={`transition-[background-color,box-shadow] duration-200 hover:bg-secondary/50 hover:shadow-[inset_3px_0_0_0_hsl(var(--primary))] ${item.drawing?.png_path ? 'cursor-pointer' : 'cursor-default'}`}
                                    >
                                        {(() => {
                                            const matched = Boolean(item.drawing?.id);
                                            const canShowUnmatched = hasUploadedDrawings && !matched;
                                            const isEditing = editingCatalogId === item.catalog_id;
                                            return (
                                                <>
                                        {isBatchMode && (
                                            <td className="px-4 py-3 align-middle text-center">
                                                <input
                                                    type="checkbox"
                                                    className="h-4 w-4 align-middle accent-primary"
                                                    checked={selectedCatalogIds.has(item.catalog_id)}
                                                    onChange={(e) => toggleSelectRow(item.catalog_id, e.target.checked)}
                                                />
                                            </td>
                                        )}
                                        <td className="px-6 py-0 font-mono text-muted-foreground align-middle text-center">
                                            <div className="h-full min-h-[56px] flex items-center justify-center">
                                                {index + 1}
                                            </div>
                                        </td>
                                        <td className="px-6 py-3 font-medium text-foreground align-middle">{item.sheet_no || '-'}</td>
                                        <td className="px-6 py-3 text-foreground align-middle">{item.sheet_name || '-'}</td>
                                        <td className="px-6 py-3 align-middle text-center">
                                            <div className="flex items-center justify-center min-h-8 gap-2">
                                                {canShowUnmatched && !isEditing && (
                                                    <Button
                                                        variant="ghost"
                                                        size="icon"
                                                        className="h-8 w-8 rounded-none"
                                                        onClick={() => startEditCatalogMatch(item.catalog_id)}
                                                        title="修改匹配"
                                                    >
                                                        <Pencil className="w-3.5 h-3.5" />
                                                    </Button>
                                                )}

                                                {isEditing ? (
                                                    <div className="flex items-center gap-2">
                                                        <Select value={selectedDrawingId} onValueChange={setSelectedDrawingId}>
                                                            <SelectTrigger className="w-[260px] h-8 rounded-none bg-white border-border shadow-none text-[12px]">
                                                                <SelectValue placeholder={drawingOptions.length ? '选择图纸匹配到目录' : '暂无可匹配图纸'} />
                                                            </SelectTrigger>
                                                            <SelectContent className="rounded-none border-border shadow-md">
                                                                {drawingOptions.map(opt => (
                                                                    <SelectItem key={opt.value} value={opt.value} className="text-[12px] rounded-none">
                                                                        {opt.label}
                                                                    </SelectItem>
                                                                ))}
                                                            </SelectContent>
                                                        </Select>
                                                        <Button
                                                            size="sm"
                                                            className="h-8 rounded-none text-[12px] px-3"
                                                            disabled={!selectedDrawingId || !drawingOptions.length || savingCatalogId === item.catalog_id}
                                                            onClick={() => saveCatalogMatch(item)}
                                                        >
                                                            {savingCatalogId === item.catalog_id ? '保存中...' : '保存'}
                                                        </Button>
                                                        <Button
                                                            variant="ghost"
                                                            size="sm"
                                                            className="h-8 rounded-none text-[12px] px-2"
                                                            onClick={cancelEditCatalogMatch}
                                                        >
                                                            取消
                                                        </Button>
                                                    </div>
                                                ) : (
                                                    matched ? (
                                                        <span className="inline-flex items-center px-2 py-0.5 border border-success/30 bg-success/10 text-success text-[12px] font-sans">
                                                            已匹配
                                                        </span>
                                                    ) : canShowUnmatched ? (
                                                        <span className="inline-flex items-center px-2 py-0.5 border border-amber-300 bg-amber-50 text-amber-700 text-[12px] font-medium font-sans">
                                                            未匹配
                                                        </span>
                                                    ) : (
                                                        <span className="inline-flex items-center px-2 py-0.5 border border-muted/30 bg-secondary text-muted-foreground text-[12px] font-sans">
                                                            —
                                                        </span>
                                                    )
                                                )}
                                            </div>
                                        </td>
                                        <td className="px-6 py-3 align-middle text-center">
                                            {item.drawing?.png_path ? (
                                                <span className="inline-flex items-center px-2 py-0.5 border border-success/30 bg-success/10 text-success text-[12px] font-sans">
                                                    已解析
                                                </span>
                                            ) : (
                                                <span className="inline-flex items-center px-2 py-0.5 border border-muted/30 bg-secondary text-muted-foreground text-[12px] font-sans">
                                                    —
                                                </span>
                                            )}
                                        </td>
                                        <td className="px-6 py-3 align-middle text-center">
                                            {item.json?.json_path ? (
                                                <span className="inline-flex items-center px-2 py-0.5 border border-success/30 bg-success/10 text-success text-[12px] font-sans">
                                                    已提取
                                                </span>
                                            ) : (
                                                <span className="inline-flex items-center px-2 py-0.5 border border-muted/30 bg-secondary text-muted-foreground text-[12px] font-sans">
                                                    —
                                                </span>
                                            )}
                                        </td>
                                        <td className="px-6 py-3 align-middle text-center">
                                            <div className="flex items-center justify-center min-h-8 gap-2">
                                                <DropdownMenu>
                                                    <DropdownMenuTrigger asChild>
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            className="h-10 w-10 rounded-lg border-0 bg-transparent p-0 shadow-none hover:bg-secondary data-[state=open]:bg-secondary focus-visible:ring-0"
                                                        >
                                                            <MoreVertical className="w-4 h-4" />
                                                        </Button>
                                                    </DropdownMenuTrigger>
                                                    <DropdownMenuContent align="end" className="w-44 rounded-none">
                                                        <DropdownMenuItem
                                                            disabled={!item.drawing?.png_path}
                                                            onClick={() => onPreviewDrawing(item)}
                                                        >
                                                            <Eye className="w-4 h-4" />
                                                            查看图纸
                                                        </DropdownMenuItem>
                                                        <DropdownMenuSeparator />
                                                        <DropdownMenuItem
                                                            variant="destructive"
                                                            disabled={!item.drawing?.id || deletingKey !== null}
                                                            onClick={() => item.drawing?.id && handleDeleteDrawing(
                                                                item.drawing.id,
                                                                `${item.sheet_no || '未识别图号'} - ${item.sheet_name || '未识别图名'}`
                                                            )}
                                                        >
                                                            <Trash2 className="w-4 h-4" />
                                                            {item.drawing?.id && deletingKey === `pdf-${item.drawing.id}` ? '删除中...' : '删除PDF'}
                                                        </DropdownMenuItem>
                                                        <DropdownMenuItem
                                                            variant="destructive"
                                                            disabled={!item.json?.id || deletingKey !== null}
                                                            onClick={() => item.json?.id && handleDeleteJson(
                                                                item.json.id,
                                                                `${item.sheet_no || '未识别图号'} - ${item.sheet_name || '未识别图名'}`
                                                            )}
                                                        >
                                                            <Trash2 className="w-4 h-4" />
                                                            {item.json?.id && deletingKey === `dwg-${item.json.id}` ? '删除中...' : '删除DWG'}
                                                        </DropdownMenuItem>
                                                    </DropdownMenuContent>
                                                </DropdownMenu>
                                            </div>
                                        </td>
                                                </>
                                            );
                                        })()}
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </ScrollArea>
            </Card>

            <AlertDialog
                open={Boolean(deleteConfirmAction)}
                onOpenChange={(open) => {
                    if (!open && !(deleteDialogCopy?.isDeleting)) setDeleteConfirmAction(null);
                }}
            >
                <AlertDialogContent className="max-w-[560px] rounded-none border border-border bg-white p-0 shadow-lg">
                    <AlertDialogHeader className="items-start gap-4 px-7 pt-7 text-left">
                        <AlertDialogTitle className="text-[22px] font-semibold leading-none text-zinc-900">
                            {deleteDialogCopy?.title}
                        </AlertDialogTitle>
                        <AlertDialogDescription className="text-[14px] leading-6 text-zinc-600">
                            {deleteDialogCopy?.description}
                        </AlertDialogDescription>
                    </AlertDialogHeader>

                    <div className="mx-7 mt-5 rounded-none border border-border bg-secondary px-4 py-3.5 text-[14px] text-zinc-700">
                        <span className="text-zinc-500">对象：</span>
                        <span className="font-medium text-zinc-900">{deleteDialogCopy?.targetLabel}</span>
                    </div>

                    <AlertDialogFooter className="mt-7 flex-row justify-end gap-3 border-t border-zinc-100 px-7 py-5">
                        <AlertDialogCancel
                            disabled={deleteDialogCopy?.isDeleting}
                            className="h-10 rounded-none border-border bg-white px-6 text-[15px] font-medium text-zinc-700 hover:bg-secondary"
                        >
                            取消
                        </AlertDialogCancel>
                        <AlertDialogAction
                            onClick={handleConfirmDelete}
                            disabled={deleteDialogCopy?.isDeleting}
                            className="h-10 rounded-none bg-red-600 px-6 text-[15px] font-semibold text-white hover:bg-red-700"
                        >
                            {deleteDialogCopy?.isDeleting ? deleteDialogCopy.deletingText : deleteDialogCopy?.confirmText}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}
