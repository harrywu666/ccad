import { Eye, FileImage, X } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import AnnotatedDrawingPreviewCanvas from './annotated-canvas';
import type { PreviewDrawing } from '../../hooks/useDrawingPreview';

interface InlineDrawingPreviewPanelProps {
  projectId: string;
  auditVersion: number;
  availableVersions: number[];
  previewSessionKey: string;
  title: string;
  description: string;
  missingReason?: string | null;
  drawingA: PreviewDrawing | null;
  drawingB?: PreviewDrawing | null;
  extraSourceAnchors?: any[];
  extraTargetAnchors?: any[];
  activeView: 'a' | 'b';
  onViewChange: (view: 'a' | 'b') => void;
  onClose: () => void;
}

export default function InlineDrawingPreviewPanel({
  projectId,
  auditVersion,
  availableVersions,
  previewSessionKey,
  title,
  description,
  missingReason = null,
  drawingA,
  drawingB = null,
  extraSourceAnchors,
  extraTargetAnchors,
  activeView,
  onViewChange,
  onClose,
}: InlineDrawingPreviewPanelProps) {
  const [overlayVersions, setOverlayVersions] = useState<number[]>([]);
  const activeDrawing = activeView === 'b' ? drawingB : drawingA;

  const displayDrawing = activeDrawing;

  const hasDrawingA = Boolean(drawingA);
  const hasDrawingB = Boolean(drawingB);
  const anchorHint = (() => {
    if (!displayDrawing) return null;
    if (displayDrawing.focusAnchorStatus === 'pdf_visual_mismatch') {
      return '当前PDF页面未检测到对应可见标记，DWG结构数据和PDF出图内容可能不一致。';
    }
    if (displayDrawing.focusAnchorStatus === 'pdf_low_confidence') {
      return '当前已标出一个自动估计位置，但这张PDF页和DWG布局的配准置信度较低，位置可能仍有偏差。';
    }
    if (displayDrawing.focusAnchorStatus === 'layout_fallback' || displayDrawing.focusAnchorStatus === 'layout_only') {
      return '当前定位仍来自布局坐标回退，和PDF页面可能存在偏差。';
    }
    return null;
  })();

  const toggleOverlayVersion = (version: number) => {
    setOverlayVersions((prev) =>
      prev.includes(version) ? prev.filter((v) => v !== version) : [...prev, version],
    );
  };

  return (
    <aside className="self-start xl:sticky xl:top-24 h-[calc(100vh-132px)] min-h-[760px] max-h-[1100px] border border-border bg-white flex flex-col">
      <div className="px-5 py-3 border-b border-border flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold text-foreground truncate">
            {displayDrawing ? `${displayDrawing.sheetNo} · ${displayDrawing.sheetName}` : '这条问题没找到对应图纸，暂时看不了'}
          </div>
          {description ? (
            <div className="mt-1 text-[12px] text-muted-foreground truncate">{description}</div>
          ) : null}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <Button
            variant={activeView === 'a' ? 'default' : 'outline'}
            className="rounded-none h-7 px-2.5 text-[12px] shadow-none"
            onClick={() => onViewChange('a')}
            disabled={!hasDrawingA}
          >
            A图
          </Button>
          {hasDrawingB ? (
            <Button
              variant={activeView === 'b' ? 'default' : 'outline'}
              className="rounded-none h-7 px-2.5 text-[12px] shadow-none"
              onClick={() => onViewChange('b')}
            >
              B图
            </Button>
          ) : null}
          <Button
            variant="ghost"
            size="icon"
            className="rounded-none h-7 w-7"
            onClick={onClose}
            aria-label={title || description || '关闭看图'}
          >
            <X className="w-4 h-4" />
          </Button>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex flex-col">
        {displayDrawing ? (
          <AnnotatedDrawingPreviewCanvas
            key={`${previewSessionKey}-${activeView}-${displayDrawing.drawingId}-v${auditVersion}`}
            projectId={projectId}
            previewDrawing={displayDrawing}
            auditVersion={auditVersion}
            availableVersions={availableVersions}
            overlayVersions={overlayVersions}
            onToggleOverlayVersion={toggleOverlayVersion}
            extraAnchors={activeView === 'b' ? extraTargetAnchors : extraSourceAnchors}
          />
        ) : (
          <div className="h-full bg-secondary/20 p-6 flex items-center justify-center">
            <div className="w-full max-w-[360px] border border-border bg-white p-8 text-center">
              <div className="w-12 h-12 mx-auto mb-4 border border-border flex items-center justify-center">
                <FileImage className="w-5 h-5 text-muted-foreground" />
              </div>
              <h4 className="text-[16px] font-semibold text-foreground mb-2">当前没有可查看图纸</h4>
              <p className="text-[13px] leading-6 text-muted-foreground">
                点左侧“查看图纸”，这里就会显示对应图纸。如果这条问题没有匹配到图纸，也会在这里说明。
              </p>
            </div>
          </div>
        )}
      </div>

      {!displayDrawing ? (
        <div className="border-t border-border px-6 py-4 text-[12px] text-muted-foreground flex items-center gap-2">
          <Eye className="w-4 h-4" />
          这条问题没有找到对应图纸，暂时只能先看文字描述。
        </div>
      ) : null}

      {displayDrawing && missingReason === 'missing_target_drawing' ? (
        <div className="border-t border-border px-6 py-4 text-[12px] text-muted-foreground flex items-center gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <Eye className="w-4 h-4 shrink-0" />
            <span className="truncate">目标图不存在，当前已自动定位到源图里的出错索引位置。</span>
          </div>
        </div>
      ) : null}

      {displayDrawing && anchorHint ? (
        <div className="border-t border-border px-6 py-4 text-[12px] text-amber-700 bg-amber-50/70 flex items-center gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <Eye className="w-4 h-4 shrink-0" />
            <span className="truncate">{anchorHint}</span>
          </div>
        </div>
      ) : null}
    </aside>
  );
}
