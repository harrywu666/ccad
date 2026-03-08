/**
 * 画布浮动控件：工具栏（左上）、缩放控件（右下）。
 */

import { ChevronDown, Layers, Minus, Pencil, Plus, Trash2, Type, Undo2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

type ImageStatus = 'loading' | 'ready' | 'error';

interface DrawingCanvasLoadingOverlayProps {
  imageStatus: ImageStatus;
  loadErrorMessage: string | null;
}

interface DrawingCanvasFloatingControlsProps {
  historyDepth: number;
  brushWidth: number;
  textSize: number;
  zoomPercent: number;
  minBrushWidth: number;
  maxBrushWidth: number;
  minTextSize: number;
  maxTextSize: number;
  auditVersion: number;
  availableVersions: number[];
  overlayVersions: number[];
  onUndo: () => void;
  onClear: () => void;
  onBrushDown: () => void;
  onBrushUp: () => void;
  onTextDown: () => void;
  onTextUp: () => void;
  onZoomOut: () => void;
  onZoomIn: () => void;
  onToggleOverlayVersion: (version: number) => void;
}

export function DrawingCanvasLoadingOverlay({
  imageStatus,
  loadErrorMessage,
}: DrawingCanvasLoadingOverlayProps) {
  if (imageStatus === 'ready') return null;

  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center px-8 text-center bg-white/95">
      <div className="space-y-2">
        <div className="text-[16px] font-semibold text-foreground">
          {imageStatus === 'loading' ? '图纸正在加载' : '图纸加载失败'}
        </div>
        <div className="text-[13px] leading-6 text-muted-foreground">
          {imageStatus === 'loading'
            ? '右侧正在读取这张图纸和它的笔记，请稍等。'
            : '这张图纸没有成功显示出来。请刷新后再试一次。'}
        </div>
        {imageStatus === 'error' && loadErrorMessage ? (
          <div className="text-[12px] text-muted-foreground">{loadErrorMessage}</div>
        ) : null}
      </div>
    </div>
  );
}

export function DrawingCanvasFloatingControls({
  historyDepth,
  brushWidth,
  textSize,
  zoomPercent,
  minBrushWidth,
  maxBrushWidth,
  minTextSize,
  maxTextSize,
  auditVersion,
  availableVersions,
  overlayVersions,
  onUndo,
  onClear,
  onBrushDown,
  onBrushUp,
  onTextDown,
  onTextUp,
  onZoomOut,
  onZoomIn,
  onToggleOverlayVersion,
}: DrawingCanvasFloatingControlsProps) {
  const otherVersions = availableVersions.filter((v) => v !== auditVersion);

  return (
    <>
      {/* 工具栏 - 左上角 */}
      <div className="pointer-events-none absolute left-3 top-3 z-20 flex items-start gap-2">
        <div className="pointer-events-auto flex items-center gap-1 border border-border bg-white/95 p-1 shadow-sm">
          <Button
            variant="outline"
            size="sm"
            className="rounded-none h-7 w-7 p-0 shadow-none"
            onClick={onUndo}
            disabled={historyDepth <= 1}
            aria-label="撤销"
            title="撤销"
          >
            <Undo2 className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="rounded-none h-7 w-7 p-0 text-destructive hover:text-destructive shadow-none"
            onClick={onClear}
            aria-label="清空笔记"
            title="清空笔记"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>

          <span className="mx-0.5 h-4 w-px bg-border" />

          <Pencil className="h-3 w-3 text-muted-foreground ml-1" />
          <Button
            variant="outline"
            size="sm"
            className="rounded-none h-7 w-7 p-0 shadow-none"
            onClick={onBrushDown}
            disabled={brushWidth <= minBrushWidth}
            aria-label="减小画笔粗细"
          >
            <Minus className="h-3.5 w-3.5" />
          </Button>
          <span className="min-w-[36px] text-center text-[11px] text-muted-foreground">{brushWidth}px</span>
          <Button
            variant="outline"
            size="sm"
            className="rounded-none h-7 w-7 p-0 shadow-none"
            onClick={onBrushUp}
            disabled={brushWidth >= maxBrushWidth}
            aria-label="增大画笔粗细"
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>

          <span className="mx-0.5 h-4 w-px bg-border" />

          <Type className="h-3 w-3 text-muted-foreground ml-1" />
          <Button
            variant="outline"
            size="sm"
            className="rounded-none h-7 w-7 p-0 shadow-none"
            onClick={onTextDown}
            disabled={textSize <= minTextSize}
            aria-label="减小默认文字大小"
          >
            <Minus className="h-3.5 w-3.5" />
          </Button>
          <span className="min-w-[36px] text-center text-[11px] text-muted-foreground">{textSize}px</span>
          <Button
            variant="outline"
            size="sm"
            className="rounded-none h-7 w-7 p-0 shadow-none"
            onClick={onTextUp}
            disabled={textSize >= maxTextSize}
            aria-label="增大默认文字大小"
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>

          {otherVersions.length > 0 ? (
            <>
              <span className="mx-0.5 h-4 w-px bg-border" />
              <DrawingOverlayVersionControl
                auditVersion={auditVersion}
                availableVersions={availableVersions}
                overlayVersions={overlayVersions}
                onToggleOverlayVersion={onToggleOverlayVersion}
                inToolbar
              />
            </>
          ) : null}
        </div>
      </div>

      {/* 缩放控件 - 右下角 */}
      <div className="pointer-events-none absolute right-3 bottom-3 z-20">
        <div className="pointer-events-auto flex items-center gap-1 border border-border bg-white/95 p-1 shadow-sm">
          <Button
            variant="outline"
            size="sm"
            className="rounded-none h-6 w-6 p-0 shadow-none"
            onClick={onZoomOut}
            aria-label="缩小"
          >
            <Minus className="h-3 w-3" />
          </Button>
          <span className="min-w-[42px] text-center text-[11px] text-muted-foreground">{zoomPercent}%</span>
          <Button
            variant="outline"
            size="sm"
            className="rounded-none h-6 w-6 p-0 shadow-none"
            onClick={onZoomIn}
            aria-label="放大"
          >
            <Plus className="h-3 w-3" />
          </Button>
        </div>
      </div>
    </>
  );
}

interface DrawingOverlayVersionControlProps {
  auditVersion: number;
  availableVersions: number[];
  overlayVersions: number[];
  onToggleOverlayVersion: (version: number) => void;
  inToolbar?: boolean;
}

export function DrawingOverlayVersionControl({
  auditVersion,
  availableVersions,
  overlayVersions,
  onToggleOverlayVersion,
  inToolbar = false,
}: DrawingOverlayVersionControlProps) {
  const otherVersions = availableVersions.filter((v) => v !== auditVersion);

  if (otherVersions.length === 0) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={`rounded-none h-7 px-2 text-[12px] shadow-none gap-1 border border-border ${inToolbar ? 'bg-transparent' : 'bg-white'}`}
        >
          <Layers className="h-3.5 w-3.5" />
          叠加标记
          {overlayVersions.length > 0 ? (
            <span className="ml-0.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] text-white">
              {overlayVersions.length}
            </span>
          ) : null}
          <ChevronDown className="h-3.5 w-3.5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[140px]">
        <DropdownMenuLabel className="text-[11px] text-muted-foreground">
          显示其他版本标记
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {otherVersions.map((v) => (
          <DropdownMenuCheckboxItem
            key={v}
            checked={overlayVersions.includes(v)}
            onCheckedChange={() => onToggleOverlayVersion(v)}
            className="text-xs"
          >
            v{v} 标记
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
