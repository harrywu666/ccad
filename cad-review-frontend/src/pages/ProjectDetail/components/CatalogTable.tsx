// src/pages/ProjectDetail/components/CatalogTable.tsx
import { type MouseEvent as ReactMouseEvent, useCallback, useEffect, useRef, useState } from 'react';
import { Pencil, Plus, Save, Trash2, CheckCircle, RefreshCw, CornerUpLeft, GripVertical } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Card } from '@/components/ui/card';
import type { CatalogItem } from '@/types';
import * as api from '@/api';

type CatalogDraftItem = {
    id?: string;
    sheet_no: string;
    sheet_name: string;
};

interface CatalogTableProps {
    projectId?: string;
    catalog: CatalogItem[];
    isLocked: boolean;
    isEditing: boolean;
    draft: CatalogDraftItem[];
    saving: boolean;
    error: string;
    onStartEdit: () => void;
    onCancelEdit: () => void;
    onSaveEdit: () => void;
    onAddRow: () => void;
    onRemoveRow: (index: number) => void;
    onUpdateField: (index: number, field: 'sheet_no' | 'sheet_name', value: string) => void;
    onLock: () => void;
    onReupload?: () => void;
    reuploadDisabled?: boolean;
    doubleColumnView?: boolean;
}

type ColumnWidths = {
    sheetNo: number;
};

const SEQ_COLUMN_WIDTH = 96;
const DEFAULT_WIDTHS: ColumnWidths = { sheetNo: 180 };
const MIN_WIDTHS: ColumnWidths = { sheetNo: 120 };
const MAX_WIDTHS: ColumnWidths = { sheetNo: 420 };

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

const sanitizeWidths = (raw: any): ColumnWidths => ({
    sheetNo: clamp(Number(raw?.sheetNo ?? DEFAULT_WIDTHS.sheetNo), MIN_WIDTHS.sheetNo, MAX_WIDTHS.sheetNo),
});

function ColumnResizeHandle({
    onMouseDown,
    label,
}: {
    onMouseDown: (event: ReactMouseEvent<HTMLButtonElement>) => void;
    label: string;
}) {
    return (
        <button
            type="button"
            aria-label={label}
            title={label}
            className="absolute -right-2 top-1/2 z-20 h-7 w-4 -translate-y-1/2 cursor-col-resize touch-none select-none border-0 bg-transparent p-0 text-muted-foreground hover:text-foreground"
            onMouseDown={onMouseDown}
        >
            <GripVertical className="mx-auto h-3.5 w-3.5" />
        </button>
    );
}

export default function CatalogTable({
    projectId,
    catalog,
    isLocked,
    isEditing,
    draft,
    saving,
    error,
    onStartEdit,
    onCancelEdit,
    onSaveEdit,
    onAddRow,
    onRemoveRow,
    onUpdateField,
    onLock,
    onReupload,
    reuploadDisabled = false,
    doubleColumnView = false,
}: CatalogTableProps) {
    const [columnWidths, setColumnWidths] = useState<ColumnWidths>(DEFAULT_WIDTHS);
    const draggingRef = useRef<{ key: 'sheetNo'; startX: number; startWidth: number } | null>(null);
    const latestWidthsRef = useRef<ColumnWidths>(DEFAULT_WIDTHS);
    const currentRows = isEditing ? draft : catalog;
    const splitIndex = Math.ceil(currentRows.length / 2);
    const leftRows = currentRows.slice(0, splitIndex);
    const rightRows = currentRows.slice(splitIndex);
    const pairedRows = Array.from({ length: Math.max(leftRows.length, rightRows.length) }, (_, index) => ({
        left: leftRows[index],
        right: rightRows[index],
    }));

    useEffect(() => {
        latestWidthsRef.current = columnWidths;
    }, [columnWidths]);

    useEffect(() => {
        let cancelled = false;
        if (!projectId) return;
        const loadPreferences = async () => {
            try {
                const res = await api.getProjectUiPreferences(projectId);
                const saved = sanitizeWidths(res?.preferences?.catalog_table?.column_widths);
                if (!cancelled) {
                    setColumnWidths(saved);
                }
            } catch {
                // keep default widths
            }
        };
        void loadPreferences();
        return () => {
            cancelled = true;
        };
    }, [projectId]);

    const persistWidths = useCallback(async (widths: ColumnWidths) => {
        if (!projectId) return;
        try {
            await api.updateProjectUiPreferences(projectId, {
                catalog_table: {
                    column_widths: widths,
                },
            });
        } catch {
            // ignore save failures to avoid blocking interaction
        }
    }, [projectId]);

    const beginResize = (event: ReactMouseEvent<HTMLButtonElement>) => {
        event.preventDefault();
        event.stopPropagation();
        draggingRef.current = {
            key: 'sheetNo',
            startX: event.clientX,
            startWidth: latestWidthsRef.current.sheetNo,
        };
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    };

    useEffect(() => {
        const onMouseMove = (event: MouseEvent) => {
            const dragging = draggingRef.current;
            if (!dragging) return;
            const delta = event.clientX - dragging.startX;
            const nextWidth = clamp(
                dragging.startWidth + delta,
                MIN_WIDTHS[dragging.key],
                MAX_WIDTHS[dragging.key]
            );
            setColumnWidths(prev => ({ ...prev, [dragging.key]: nextWidth }));
        };

        const onMouseUp = () => {
            if (!draggingRef.current) return;
            draggingRef.current = null;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            void persistWidths(latestWidthsRef.current);
        };

        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
        return () => {
            window.removeEventListener('mousemove', onMouseMove);
            window.removeEventListener('mouseup', onMouseUp);
        };
    }, [persistWidths]);

    return (
        <div className="flex-1 min-w-[600px] flex flex-col gap-6 bg-secondary/30 p-8 border border-border">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <h2 className="text-[18px] font-semibold font-sans text-foreground mb-1">
                        {isLocked ? '目录数据 (已锁定)' : '识别结果 (可编辑)'}
                    </h2>
                    <p className="text-[13px] text-muted-foreground font-sans">
                        {isLocked
                            ? `共 ${catalog.length} 条有效图纸记录`
                            : '检查数据正确性，随时修改或锁定'}
                    </p>
                </div>

                <div className="flex items-center gap-2">
                    {isEditing ? (
                        <>
                            <Button
                                variant="outline"
                                size="icon"
                                onClick={onAddRow}
                                disabled={saving}
                                className="rounded-none bg-white h-9 w-9 border-border"
                                title="新增行"
                            >
                                <Plus className="h-4 w-4" />
                            </Button>
                            <Button
                                variant="outline"
                                size="icon"
                                onClick={onCancelEdit}
                                disabled={saving}
                                className="rounded-none text-muted-foreground h-9 w-9 bg-white border-border shadow-none"
                                title="取消"
                            >
                                <CornerUpLeft className="h-4 w-4" />
                            </Button>
                            <Button
                                onClick={onSaveEdit}
                                disabled={saving}
                                className="bg-primary hover:bg-primary/90 rounded-none h-9 w-9 p-0 flex items-center justify-center shadow-none"
                                title="保存修改"
                            >
                                {saving ? <RefreshCw className="h-4 w-4 animate-spin text-white" /> : <Save className="h-4 w-4 text-white" />}
                            </Button>
                        </>
                    ) : (
                        <>
                            {(catalog.length > 0 || isLocked) && (
                                <Button
                                    variant="outline"
                                    size="icon"
                                    onClick={onStartEdit}
                                    className="rounded-none bg-white h-9 w-9 border-border shadow-none"
                                    title="修改目录"
                                >
                                    <Pencil className="h-4 w-4" />
                                </Button>
                            )}
                            {catalog.length > 0 && onReupload && (
                                <Button
                                    variant="outline"
                                    onClick={onReupload}
                                    disabled={reuploadDisabled}
                                    className="rounded-none bg-white h-9 px-4 border-border shadow-none"
                                >
                                    重新上传
                                </Button>
                            )}
                            {catalog.length > 0 && !isLocked && (
                                <Button onClick={onLock} className="rounded-none bg-success hover:bg-success/90 text-white h-9 px-4 shadow-none">
                                    <CheckCircle className="h-4 w-4 mr-2" />
                                    锁定目录
                                </Button>
                            )}
                        </>
                    )}
                </div>
            </div>

            {error && <p className="text-[13px] text-primary font-sans">{error}</p>}

            <Card className="border-border shadow-none rounded-none flex-1 overflow-hidden flex flex-col min-h-[400px]">
                <ScrollArea className="flex-1">
                    {doubleColumnView && !isEditing && currentRows.length > 0 ? (
                        <table className="w-full table-fixed text-[13px] font-sans text-left">
                            <colgroup>
                                <col style={{ width: `${SEQ_COLUMN_WIDTH}px` }} />
                                <col style={{ width: `${columnWidths.sheetNo}px` }} />
                                <col />
                                <col style={{ width: `${SEQ_COLUMN_WIDTH}px` }} />
                                <col style={{ width: `${columnWidths.sheetNo}px` }} />
                                <col />
                            </colgroup>
                            <thead className="bg-zinc-100 sticky top-0 border-b border-border z-10">
                                <tr>
                                    <th className="relative px-6 py-4 font-semibold text-muted-foreground text-center">序号</th>
                                    <th className="relative px-6 py-4 font-semibold text-muted-foreground">
                                        图号
                                        <ColumnResizeHandle
                                            label="拖拽调整图号列宽"
                                            onMouseDown={beginResize}
                                        />
                                    </th>
                                    <th className="px-6 py-4 font-semibold text-muted-foreground">图名</th>
                                    <th className="relative border-l border-border px-6 py-4 font-semibold text-muted-foreground text-center">序号</th>
                                    <th className="relative px-6 py-4 font-semibold text-muted-foreground">图号</th>
                                    <th className="px-6 py-4 font-semibold text-muted-foreground">图名</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border bg-white">
                                {pairedRows.map(({ left, right }, index) => (
                                    <tr
                                        key={`${left?.id || `left-${index}`}-${right?.id || `right-${index}`}`}
                                        className="cursor-pointer transition-[background-color,box-shadow] duration-200 hover:bg-secondary/50 hover:shadow-[inset_3px_0_0_0_hsl(var(--primary))]"
                                    >
                                        <td className="px-6 py-0 font-mono text-muted-foreground align-middle">
                                            <div className="flex min-h-[56px] items-center justify-center">
                                                {left ? index + 1 : ''}
                                            </div>
                                        </td>
                                        <td className="px-6 py-0 align-middle">
                                            <div className="flex min-h-[56px] items-center py-3">
                                                <span className="font-medium text-foreground">{left?.sheet_no || ''}</span>
                                            </div>
                                        </td>
                                        <td className="px-6 py-0 align-middle">
                                            <div className="flex min-h-[56px] items-center py-3">
                                                <span className="text-foreground">{left?.sheet_name || ''}</span>
                                            </div>
                                        </td>
                                        <td className="border-l border-border px-6 py-0 font-mono text-muted-foreground align-middle">
                                            <div className="flex min-h-[56px] items-center justify-center">
                                                {right ? splitIndex + index + 1 : ''}
                                            </div>
                                        </td>
                                        <td className="px-6 py-0 align-middle">
                                            <div className="flex min-h-[56px] items-center py-3">
                                                <span className="font-medium text-foreground">{right?.sheet_no || ''}</span>
                                            </div>
                                        </td>
                                        <td className="px-6 py-0 align-middle">
                                            <div className="flex min-h-[56px] items-center py-3">
                                                <span className="text-foreground">{right?.sheet_name || ''}</span>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    ) : (
                        <table className="w-full table-fixed text-[13px] font-sans text-left">
                            <colgroup>
                                <col style={{ width: `${SEQ_COLUMN_WIDTH}px` }} />
                                <col style={{ width: `${columnWidths.sheetNo}px` }} />
                                <col />
                                {isEditing && <col style={{ width: '96px' }} />}
                            </colgroup>
                            <thead className="bg-zinc-100 sticky top-0 border-b border-border z-10">
                                <tr>
                                    <th className="relative px-6 py-4 font-semibold text-muted-foreground text-center">序号</th>
                                    <th className="relative px-6 py-4 font-semibold text-muted-foreground">
                                        图号
                                        <ColumnResizeHandle
                                            label="拖拽调整图号列宽"
                                            onMouseDown={beginResize}
                                        />
                                    </th>
                                    <th className="px-6 py-4 font-semibold text-muted-foreground">图名</th>
                                    {isEditing && <th className="px-6 py-4 font-semibold text-muted-foreground w-24 text-center">操作</th>}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border bg-white">
                                {currentRows.length === 0 ? (
                                    <tr>
                                        <td colSpan={isEditing ? 4 : 3} className="px-6 py-12 text-center text-muted-foreground">
                                            暂无数据。请在右侧上传系统识别，或点击右上角新增行手动录入。
                                        </td>
                                    </tr>
                                ) : (
                                    currentRows.map((item, index) => (
                                        <tr
                                            key={item.id || `draft-${index}`}
                                            className="cursor-pointer transition-[background-color,box-shadow] duration-200 hover:bg-secondary/50 hover:shadow-[inset_3px_0_0_0_hsl(var(--primary))]"
                                        >
                                            <td className="px-6 py-0 font-mono text-muted-foreground align-middle">
                                                <div className="h-full min-h-[56px] flex items-center justify-center">
                                                    {index + 1}
                                                </div>
                                            </td>
                                            <td className="px-6 py-3">
                                                {isEditing ? (
                                                    <Input
                                                        value={item.sheet_no || ''}
                                                        onChange={e => onUpdateField(index, 'sheet_no', e.target.value)}
                                                        placeholder="图号"
                                                        className="h-9 rounded-none border-border focus-visible:ring-1 focus-visible:ring-primary shadow-none"
                                                    />
                                                ) : (
                                                    <span className="font-medium text-foreground">{item.sheet_no || '-'}</span>
                                                )}
                                            </td>
                                            <td className="px-6 py-3">
                                                {isEditing ? (
                                                    <Input
                                                        value={item.sheet_name || ''}
                                                        onChange={e => onUpdateField(index, 'sheet_name', e.target.value)}
                                                        placeholder="图名"
                                                        className="h-9 rounded-none border-border focus-visible:ring-1 focus-visible:ring-primary shadow-none"
                                                    />
                                                ) : (
                                                    <span className="text-foreground">{item.sheet_name || '-'}</span>
                                                )}
                                            </td>
                                            {isEditing && (
                                                <td className="px-6 py-3 text-center">
                                                    <Button
                                                        variant="ghost"
                                                        size="icon"
                                                        onClick={() => onRemoveRow(index)}
                                                        className="text-muted-foreground hover:text-primary rounded-none h-8 w-8"
                                                    >
                                                        <Trash2 className="h-4 w-4" />
                                                    </Button>
                                                </td>
                                            )}
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    )}
                </ScrollArea>
            </Card>
        </div>
    );
}
