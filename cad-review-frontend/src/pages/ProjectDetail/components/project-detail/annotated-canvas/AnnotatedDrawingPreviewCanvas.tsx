/**
 * 图纸标注预览画布 —— 支持画笔绘制、文字标注和平移缩放。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Group, Image as KonvaImage, Layer, Line, Stage, Text as KonvaText, Transformer } from 'react-konva';
import type { KonvaEventObject } from 'konva/lib/Node';
import type { Text as KonvaTextNode } from 'konva/lib/shapes/Text';
import type { Transformer as KonvaTransformerNode } from 'konva/lib/shapes/Transformer';
import { TriangleAlert } from 'lucide-react';
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
import { DrawingCanvasFloatingControls, DrawingCanvasLoadingOverlay } from '../DrawingCanvasOverlay';
import type { AnnotatedDrawingPreviewCanvasProps, ExtraAnchor, TextAnnotationItem, ToolMode } from './types';
import {
  BRUSH_COLOR,
  BRUSH_WIDTH_OPTIONS,
  DEFAULT_BRUSH_WIDTH,
  DEFAULT_TEXT_SIZE,
  MAX_TEXT_SIZE,
  MIN_BRUSH_WIDTH,
  MIN_TEXT_SIZE,
  TEXT_SIZE_OPTIONS,
  makeId,
  normalizeText,
} from './constants';
import { toCanvasCloudHighlight } from './highlightRegions';
import { useAnnotationBoard } from './useAnnotationBoard';
import { useCanvasViewport } from './useCanvasViewport';
import { useIssueFocus } from './useIssueFocus';
import { useOverlayAnnotations } from './useOverlayAnnotations';

const buildCloudRectPoints = (x: number, y: number, width: number, height: number) => {
  const bumpsX = Math.max(3, Math.round(width / 48));
  const bumpsY = Math.max(3, Math.round(height / 48));
  const points: number[] = [];

  const push = (px: number, py: number) => {
    points.push(px, py);
  };

  push(x, y + height * 0.12);
  for (let idx = 0; idx < bumpsX; idx += 1) {
    const startX = x + (width / bumpsX) * idx;
    const endX = x + (width / bumpsX) * (idx + 1);
    const midX = (startX + endX) / 2;
    push(midX, y - height * 0.08);
    push(endX, y + height * 0.12);
  }
  for (let idx = 0; idx < bumpsY; idx += 1) {
    const startY = y + (height / bumpsY) * idx;
    const endY = y + (height / bumpsY) * (idx + 1);
    const midY = (startY + endY) / 2;
    push(x + width + width * 0.08, midY);
    push(x + width - width * 0.12, endY);
  }
  for (let idx = 0; idx < bumpsX; idx += 1) {
    const startX = x + width - (width / bumpsX) * idx;
    const endX = x + width - (width / bumpsX) * (idx + 1);
    const midX = (startX + endX) / 2;
    push(midX, y + height + height * 0.08);
    push(endX, y + height - height * 0.12);
  }
  for (let idx = 0; idx < bumpsY; idx += 1) {
    const startY = y + height - (height / bumpsY) * idx;
    const endY = y + height - (height / bumpsY) * (idx + 1);
    const midY = (startY + endY) / 2;
    push(x - width * 0.08, midY);
    push(x + width * 0.12, endY);
  }
  return points;
};

export default function AnnotatedDrawingPreviewCanvas({
  projectId,
  previewDrawing,
  auditVersion,
  availableVersions,
  overlayVersions,
  onToggleOverlayVersion,
  extraAnchors,
}: AnnotatedDrawingPreviewCanvasProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<import('konva/lib/Stage').Stage | null>(null);
  const transformerRef = useRef<KonvaTransformerNode | null>(null);
  const textNodesRef = useRef<Record<string, KonvaTextNode | null>>({});
  const inlineInputRef = useRef<HTMLInputElement | null>(null);
  const suppressInputBlurRef = useRef(false);
  const middleDraggingRef = useRef(false);
  const lastPointerRef = useRef<{ x: number; y: number } | null>(null);
  const drawingStrokeIdRef = useRef<string | null>(null);
  const mouseDownClientRef = useRef<{ x: number; y: number } | null>(null);
  const hasSignificantDragRef = useRef(false);
  const CLICK_THRESHOLD = 5;

  const [toolMode, setToolMode] = useState<ToolMode>('pan');
  const [brushWidth, setBrushWidth] = useState(DEFAULT_BRUSH_WIDTH);
  const [textSize, setTextSize] = useState(DEFAULT_TEXT_SIZE);
  const [selectedTextId, setSelectedTextId] = useState<string | null>(null);
  const [editingTextId, setEditingTextId] = useState<string | null>(null);
  const [editingTextValue, setEditingTextValue] = useState('');
  const [editingTextOriginal, setEditingTextOriginal] = useState('');
  const [editingTextIsNew, setEditingTextIsNew] = useState(false);
  const [editingTextAnchor, setEditingTextAnchor] = useState<{ x: number; y: number; fontSize: number } | null>(null);
  const [clearDialogOpen, setClearDialogOpen] = useState(false);

  const {
    imageStatus,
    imageAsset,
    loadErrorMessage,
    items,
    historyDepth,
    itemsRef,
    syncItems,
    commitItemsChange,
    handleUndo,
    clearBoard,
  } = useAnnotationBoard({ projectId, previewDrawing, auditVersion });

  const {
    stageSize,
    view,
    setView,
    viewRef,
    zoomPercent,
    toImagePoint,
    getPointerInStage,
    handleWheel,
    handleZoomByFactor,
  } = useCanvasViewport({ viewportRef, stageRef, imageAsset, imageStatus });

  const overlayLayers = useOverlayAnnotations({
    projectId,
    sheetNo: previewDrawing.sheetNo,
    overlayVersions,
  });

  useIssueFocus({
    drawingId: previewDrawing.drawingId,
    focusAnchor: previewDrawing.focusAnchor,
    focusHighlightRegion: previewDrawing.focusHighlightRegion,
    focusAnchorStatus: previewDrawing.focusAnchorStatus,
    imageAsset,
    imageStatus,
    stageSize,
    setView,
  });

  const issueHighlight = useMemo(() => {
    if (!imageAsset) return null;
    if (previewDrawing.focusAnchorStatus === 'pdf_visual_mismatch') {
      return null;
    }
    if (
      typeof previewDrawing.focusAnchor?.confidence === 'number'
      && previewDrawing.focusAnchor.confidence < 0.6
      && previewDrawing.focusAnchorStatus !== 'pdf_low_confidence'
    ) {
      return null;
    }
    return toCanvasCloudHighlight({
      imageAsset,
      key: 'primary',
      point: previewDrawing.focusAnchor?.global_pct ?? null,
      region: previewDrawing.focusHighlightRegion,
      variant: previewDrawing.focusAnchorStatus === 'pdf_low_confidence' ? 'estimated' : 'exact',
    });
  }, [imageAsset, previewDrawing.focusAnchor, previewDrawing.focusAnchorStatus, previewDrawing.focusHighlightRegion]);

  const extraHighlights = useMemo(() => {
    if (!imageAsset || !extraAnchors?.length) return [];
    return extraAnchors.map((anchor: ExtraAnchor, idx: number) => (
      toCanvasCloudHighlight({
        imageAsset,
        key: `extra-${anchor.issue_id || idx}`,
        point: anchor.global_pct ?? null,
        region: anchor.highlight_region,
        variant: 'exact',
        label: anchor.location || undefined,
      })
    )).filter(Boolean);
  }, [imageAsset, extraAnchors]);

  // ── 切换图纸时重置编辑状态 ──
  useEffect(() => {
    setToolMode('pan');
    setSelectedTextId(null);
    setEditingTextId(null);
    setEditingTextValue('');
    setEditingTextOriginal('');
    setEditingTextIsNew(false);
    setEditingTextAnchor(null);
  }, [previewDrawing.drawingId]);

  // ── 内联编辑器定位样式 ──
  const inlineEditorStyle = useMemo(() => {
    if (!editingTextAnchor) return null;
    const scale = view.scale || 1;
    const left = view.x + editingTextAnchor.x * scale;
    const top = view.y + editingTextAnchor.y * scale;
    return {
      left,
      top,
      fontSize: Math.max(16, Math.round(editingTextAnchor.fontSize * scale)),
    };
  }, [editingTextAnchor, view.scale, view.x, view.y]);

  // ── 文字内联编辑 ──
  const startInlineTextEditor = useCallback((target: TextAnnotationItem, isNew: boolean) => {
    setToolMode('text');
    setSelectedTextId(target.id);
    setEditingTextId(target.id);
    setEditingTextValue(target.text || '');
    setEditingTextOriginal(target.text || '');
    setEditingTextIsNew(isNew);
    setEditingTextAnchor({ x: target.x, y: target.y, fontSize: target.fontSize });
    suppressInputBlurRef.current = false;
  }, []);

  const finishInlineTextEditing = useCallback((shouldCommit: boolean) => {
    if (!editingTextId) return;

    const targetId = editingTextId;
    const nextValue = normalizeText(editingTextValue);
    const isNew = editingTextIsNew;
    const original = editingTextOriginal;

    setEditingTextId(null);
    setEditingTextValue('');
    setEditingTextOriginal('');
    setEditingTextIsNew(false);
    setEditingTextAnchor(null);
    setSelectedTextId(null);
    setToolMode('pan');

    if (!shouldCommit) {
      if (isNew) {
        const removed = itemsRef.current.filter((item) => item.id !== targetId);
        syncItems(removed);
      }
      return;
    }

    const finalValue = nextValue || (isNew ? '' : original);
    if (!finalValue) {
      const removed = itemsRef.current.filter((item) => item.id !== targetId);
      commitItemsChange(removed);
      return;
    }

    const updated = itemsRef.current.map((item) => {
      if (item.id !== targetId || item.type !== 'text') return item;
      return { ...item, text: finalValue, fontSize: Math.max(MIN_TEXT_SIZE, item.fontSize) };
    });
    commitItemsChange(updated);
  }, [commitItemsChange, editingTextId, editingTextIsNew, editingTextOriginal, editingTextValue, itemsRef, syncItems]);

  useEffect(() => {
    if (!editingTextId || !inlineInputRef.current) return;
    inlineInputRef.current.focus();
    inlineInputRef.current.select();
  }, [editingTextId]);

  // ── Transformer 节点同步 ──
  useEffect(() => {
    const transformer = transformerRef.current;
    if (!transformer) return;

    if (toolMode !== 'text' || !selectedTextId || editingTextId) {
      transformer.nodes([]);
      transformer.getLayer()?.batchDraw();
      return;
    }

    const node = textNodesRef.current[selectedTextId];
    if (!node) {
      transformer.nodes([]);
      transformer.getLayer()?.batchDraw();
      return;
    }
    transformer.nodes([node]);
    transformer.getLayer()?.batchDraw();
  }, [editingTextId, selectedTextId, toolMode, items]);

  // ── 鼠标事件处理 ──
  const handleMouseDown = useCallback((event: KonvaEventObject<MouseEvent>) => {
    if (event.evt.button === 1) {
      event.evt.preventDefault();
      if (editingTextId) finishInlineTextEditing(true);
      middleDraggingRef.current = true;
      lastPointerRef.current = { x: event.evt.clientX, y: event.evt.clientY };
      return;
    }

    if (event.evt.button === 2) {
      event.evt.preventDefault();
      const target = event.target;
      const targetName = target?.name();
      if (targetName === 'annotation-text') return;
      if (transformerRef.current && target?.getParent() === transformerRef.current) return;

      if (editingTextId) {
        finishInlineTextEditing(true);
        return;
      }

      const pointer = getPointerInStage(event.evt);
      if (!pointer) return;

      setSelectedTextId(null);
      const p = toImagePoint(pointer);
      const newText: TextAnnotationItem = {
        id: makeId(),
        type: 'text',
        text: '',
        x: p.x,
        y: p.y,
        fontSize: Math.max(MIN_TEXT_SIZE, textSize),
        color: BRUSH_COLOR,
      };
      syncItems([...itemsRef.current, newText]);
      startInlineTextEditor(newText, true);
      return;
    }

    if (event.evt.button !== 0) return;

    const target = event.target;
    const targetName = target?.name();
    if (targetName === 'annotation-text') return;
    if (transformerRef.current && target?.getParent() === transformerRef.current) return;

    if (editingTextId) {
      finishInlineTextEditing(true);
      return;
    }

    const pointer = getPointerInStage(event.evt);
    if (!pointer) return;

    setSelectedTextId(null);
    mouseDownClientRef.current = { x: event.evt.clientX, y: event.evt.clientY };
    hasSignificantDragRef.current = false;

    const p = toImagePoint(pointer);
    const id = makeId();
    drawingStrokeIdRef.current = id;
    setToolMode('draw');
    syncItems([
      ...itemsRef.current,
      {
        id,
        type: 'stroke' as const,
        color: BRUSH_COLOR,
        strokeWidth: Math.max(MIN_BRUSH_WIDTH, brushWidth),
        points: [p.x, p.y],
      },
    ]);
  }, [brushWidth, editingTextId, finishInlineTextEditing, getPointerInStage, itemsRef, startInlineTextEditor, syncItems, textSize, toImagePoint]);

  const handleStageClick = useCallback((_event: KonvaEventObject<MouseEvent>) => {
    // click 处理已移到 handleMouseUp 中
  }, []);

  const handleMouseMove = useCallback((event: KonvaEventObject<MouseEvent>) => {
    if (middleDraggingRef.current && lastPointerRef.current) {
      const dx = event.evt.clientX - lastPointerRef.current.x;
      const dy = event.evt.clientY - lastPointerRef.current.y;
      lastPointerRef.current = { x: event.evt.clientX, y: event.evt.clientY };
      const currentView = viewRef.current;
      setView({ x: currentView.x + dx, y: currentView.y + dy, scale: currentView.scale });
      return;
    }

    if (!drawingStrokeIdRef.current) return;

    if (!hasSignificantDragRef.current && mouseDownClientRef.current) {
      const dx = event.evt.clientX - mouseDownClientRef.current.x;
      const dy = event.evt.clientY - mouseDownClientRef.current.y;
      if (Math.sqrt(dx * dx + dy * dy) >= CLICK_THRESHOLD) {
        hasSignificantDragRef.current = true;
      }
    }

    const stage = stageRef.current;
    const pointer = stage?.getPointerPosition();
    if (!pointer) return;
    const p = toImagePoint(pointer);
    const nextItems = itemsRef.current.map((item) => {
      if (item.id !== drawingStrokeIdRef.current || item.type !== 'stroke') return item;
      return { ...item, points: [...item.points, p.x, p.y] };
    });
    syncItems(nextItems);
  }, [itemsRef, setView, syncItems, toImagePoint, viewRef]);

  const handleMouseUp = useCallback(() => {
    middleDraggingRef.current = false;
    lastPointerRef.current = null;

    const strokeId = drawingStrokeIdRef.current;
    drawingStrokeIdRef.current = null;
    const wasDrag = hasSignificantDragRef.current;
    mouseDownClientRef.current = null;
    hasSignificantDragRef.current = false;
    setToolMode('pan');

    if (!strokeId) return;

    if (wasDrag) {
      commitItemsChange(itemsRef.current);
    } else {
      const withoutStroke = itemsRef.current.filter((item) => item.id !== strokeId);
      syncItems(withoutStroke);
    }
  }, [commitItemsChange, itemsRef, syncItems]);

  const handleMouseLeave = useCallback(() => {
    middleDraggingRef.current = false;
    lastPointerRef.current = null;

    const strokeId = drawingStrokeIdRef.current;
    drawingStrokeIdRef.current = null;
    mouseDownClientRef.current = null;
    hasSignificantDragRef.current = false;
    setToolMode('pan');

    if (strokeId) {
      commitItemsChange(itemsRef.current);
    }
  }, [commitItemsChange, itemsRef]);

  // ── 清空标注 ──
  const confirmClear = useCallback(async () => {
    setClearDialogOpen(false);
    setSelectedTextId(null);
    setEditingTextId(null);
    setEditingTextValue('');
    setEditingTextOriginal('');
    setEditingTextIsNew(false);
    setEditingTextAnchor(null);
    await clearBoard();
  }, [clearBoard]);

  // ── 工具尺寸调节 ──
  const cycleBrushWidth = useCallback((direction: 'up' | 'down') => {
    setBrushWidth((prev) => {
      const idx = BRUSH_WIDTH_OPTIONS.indexOf(prev as typeof BRUSH_WIDTH_OPTIONS[number]);
      if (direction === 'up') return idx < BRUSH_WIDTH_OPTIONS.length - 1 ? BRUSH_WIDTH_OPTIONS[idx + 1] : prev;
      return idx > 0 ? BRUSH_WIDTH_OPTIONS[idx - 1] : prev;
    });
  }, []);

  const cycleTextSize = useCallback((direction: 'up' | 'down') => {
    setTextSize((prev) => {
      const idx = TEXT_SIZE_OPTIONS.indexOf(prev as typeof TEXT_SIZE_OPTIONS[number]);
      if (direction === 'up') return idx < TEXT_SIZE_OPTIONS.length - 1 ? TEXT_SIZE_OPTIONS[idx + 1] : prev;
      return idx > 0 ? TEXT_SIZE_OPTIONS[idx - 1] : prev;
    });
  }, []);

  const scaleEditingText = useCallback((direction: 'up' | 'down') => {
    if (!editingTextId) return;
    const target = itemsRef.current.find((item): item is TextAnnotationItem => (
      item.id === editingTextId && item.type === 'text'
    ));
    if (!target) return;

    const factor = direction === 'up' ? 1.1 : 1 / 1.1;
    const nextSize = Math.max(MIN_TEXT_SIZE, Math.min(MAX_TEXT_SIZE, Math.round(target.fontSize * factor)));
    if (nextSize === target.fontSize) return;

    const updated = itemsRef.current.map((item) => (
      item.id === editingTextId && item.type === 'text'
        ? { ...item, fontSize: nextSize }
        : item
    ));
    syncItems(updated);
    setEditingTextAnchor((prev) => (prev ? { x: prev.x, y: prev.y, fontSize: nextSize } : prev));
    setTextSize(nextSize);
  }, [editingTextId, itemsRef, syncItems]);

  // ── 渲染 ──
  return (
    <div className="h-full min-h-0 bg-secondary/20 p-2 flex flex-col">
      <div
        ref={viewportRef}
        className="relative flex-1 min-h-0 overflow-hidden border border-border bg-white"
      >
        <DrawingCanvasLoadingOverlay imageStatus={imageStatus} loadErrorMessage={loadErrorMessage} />

        <Stage
          ref={stageRef}
          width={stageSize.width}
          height={stageSize.height}
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onClick={handleStageClick}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseLeave}
          style={{ background: 'transparent' }}
        >
          <Layer>
            <Group x={view.x} y={view.y} scaleX={view.scale} scaleY={view.scale}>
              {imageAsset ? (
                <KonvaImage
                  image={imageAsset.source}
                  width={imageAsset.width}
                  height={imageAsset.height}
                  listening={false}
                />
              ) : null}

              {issueHighlight ? (
                <Group listening={false}>
                  <Line
                    points={buildCloudRectPoints(issueHighlight.x, issueHighlight.y, issueHighlight.width, issueHighlight.height)}
                    stroke={issueHighlight.variant === 'estimated' ? '#d97706' : '#ef4444'}
                    strokeWidth={3}
                    closed
                    tension={0.28}
                    dash={issueHighlight.variant === 'estimated' ? [8, 5] : undefined}
                    listening={false}
                  />
                  {issueHighlight.variant === 'estimated' ? (
                    <KonvaText
                      x={issueHighlight.x + issueHighlight.width + 18}
                      y={issueHighlight.y - 34}
                      text="估计位置"
                      fontSize={18}
                      fill="#b45309"
                      listening={false}
                    />
                  ) : null}
                </Group>
              ) : null}

              {extraHighlights.map((eh) => (
                <Group key={eh.key} listening={false}>
                  <Line
                    points={buildCloudRectPoints(eh.x, eh.y, eh.width, eh.height)}
                    stroke="#ef4444"
                    strokeWidth={2.5}
                    closed
                    tension={0.28}
                    listening={false}
                  />
                  {eh.label ? (
                    <KonvaText
                      x={eh.x + eh.width + 14}
                      y={eh.y - 28}
                      text={eh.label}
                      fontSize={16}
                      fill="#b91c1c"
                      listening={false}
                    />
                  ) : null}
                </Group>
              ))}

              {/* 叠加层：其他版本标注（蓝色 80% 透明度，只读） */}
              {overlayLayers.map((layer) => (
                <Group key={`overlay-${layer.version}`} opacity={0.8}>
                  {layer.items.map((item) => {
                    if (item.type === 'stroke') {
                      return (
                        <Line
                          key={`ov-${item.id}`}
                          points={item.points}
                          stroke={item.color}
                          strokeWidth={item.strokeWidth}
                          lineCap="round"
                          lineJoin="round"
                          tension={0}
                          listening={false}
                        />
                      );
                    }
                    return (
                      <KonvaText
                        key={`ov-${item.id}`}
                        text={item.text}
                        x={item.x}
                        y={item.y}
                        fontSize={Math.max(MIN_TEXT_SIZE, item.fontSize)}
                        fill={item.color}
                        listening={false}
                      />
                    );
                  })}
                </Group>
              ))}

              {/* 当前版本标注（可编辑） */}
              {items.map((item) => {
                if (item.type === 'stroke') {
                  return (
                    <Line
                      key={item.id}
                      points={item.points}
                      stroke={item.color}
                      strokeWidth={item.strokeWidth}
                      lineCap="round"
                      lineJoin="round"
                      tension={0}
                      listening={false}
                    />
                  );
                }
                return (
                  <KonvaText
                    key={item.id}
                    ref={(node) => { textNodesRef.current[item.id] = node; }}
                    name="annotation-text"
                    text={item.text}
                    x={item.x}
                    y={item.y}
                    fontSize={Math.max(MIN_TEXT_SIZE, item.fontSize)}
                    fill={item.color}
                    draggable={editingTextId !== item.id}
                    onClick={() => { setToolMode('text'); setSelectedTextId(item.id); }}
                    onTap={() => { setToolMode('text'); setSelectedTextId(item.id); }}
                    onDragStart={() => { setToolMode('text'); setSelectedTextId(item.id); }}
                    onDragEnd={(event) => {
                      const nextItems = itemsRef.current.map((entry) => (
                        entry.id === item.id && entry.type === 'text'
                          ? { ...entry, x: event.target.x(), y: event.target.y() }
                          : entry
                      ));
                      commitItemsChange(nextItems);
                    }}
                    onDblClick={() => {
                      const latest = itemsRef.current.find(
                        (entry): entry is TextAnnotationItem => entry.id === item.id && entry.type === 'text',
                      );
                      if (!latest) return;
                      startInlineTextEditor(latest, false);
                    }}
                    onTransformEnd={(event) => {
                      const node = event.target as KonvaTextNode;
                      const scale = Math.max(node.scaleX(), node.scaleY());
                      const nextFontSize = Math.max(
                        MIN_TEXT_SIZE,
                        Math.min(MAX_TEXT_SIZE, Math.round(item.fontSize * scale)),
                      );
                      node.scaleX(1);
                      node.scaleY(1);
                      const nextItems = itemsRef.current.map((entry) => (
                        entry.id === item.id && entry.type === 'text'
                          ? { ...entry, x: node.x(), y: node.y(), fontSize: nextFontSize }
                          : entry
                      ));
                      commitItemsChange(nextItems);
                      setSelectedTextId(item.id);
                    }}
                  />
                );
              })}
            </Group>

            {toolMode === 'text' ? (
              <Transformer
                ref={transformerRef}
                rotateEnabled={false}
                keepRatio
                enabledAnchors={['top-left', 'top-right', 'bottom-left', 'bottom-right']}
                borderStroke={BRUSH_COLOR}
                anchorFill="#ffffff"
                anchorStroke={BRUSH_COLOR}
                anchorSize={8}
                borderDash={[4, 4]}
                ignoreStroke
                boundBoxFunc={(oldBox, newBox) => {
                  if (newBox.width < 20 || newBox.height < 20) return oldBox;
                  return newBox;
                }}
              />
            ) : null}
          </Layer>
        </Stage>

        {editingTextId && inlineEditorStyle ? (
          <div
            className="absolute z-40"
            style={{ left: inlineEditorStyle.left, top: inlineEditorStyle.top }}
          >
            <input
              ref={inlineInputRef}
              value={editingTextValue}
              className="min-w-[220px] border border-primary bg-white/95 px-2 py-1 leading-none text-foreground shadow-sm outline-none"
              style={{ fontSize: `${inlineEditorStyle.fontSize}px` }}
              onChange={(event) => { setEditingTextValue(event.target.value); }}
              onWheel={(event) => {
                event.preventDefault();
                event.stopPropagation();
                scaleEditingText(event.deltaY < 0 ? 'up' : 'down');
              }}
              onBlur={() => {
                if (suppressInputBlurRef.current) {
                  suppressInputBlurRef.current = false;
                  return;
                }
                finishInlineTextEditing(true);
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  suppressInputBlurRef.current = true;
                  finishInlineTextEditing(true);
                } else if (event.key === 'Escape') {
                  event.preventDefault();
                  suppressInputBlurRef.current = true;
                  finishInlineTextEditing(false);
                }
              }}
              placeholder="输入文字"
            />
          </div>
        ) : null}

        <DrawingCanvasFloatingControls
          historyDepth={historyDepth}
          brushWidth={brushWidth}
          textSize={textSize}
          zoomPercent={zoomPercent}
          minBrushWidth={BRUSH_WIDTH_OPTIONS[0]}
          maxBrushWidth={BRUSH_WIDTH_OPTIONS[BRUSH_WIDTH_OPTIONS.length - 1]}
          minTextSize={TEXT_SIZE_OPTIONS[0]}
          maxTextSize={TEXT_SIZE_OPTIONS[TEXT_SIZE_OPTIONS.length - 1]}
          auditVersion={auditVersion}
          availableVersions={availableVersions}
          overlayVersions={overlayVersions}
          onUndo={handleUndo}
          onClear={() => setClearDialogOpen(true)}
          onBrushDown={() => cycleBrushWidth('down')}
          onBrushUp={() => cycleBrushWidth('up')}
          onTextDown={() => cycleTextSize('down')}
          onTextUp={() => cycleTextSize('up')}
          onZoomOut={() => handleZoomByFactor(0.9)}
          onZoomIn={() => handleZoomByFactor(1.1)}
          onToggleOverlayVersion={onToggleOverlayVersion}
        />

        <AlertDialog open={clearDialogOpen} onOpenChange={setClearDialogOpen}>
          <AlertDialogContent className="max-w-[480px] rounded-none border border-border bg-white p-0 shadow-lg">
            <AlertDialogHeader className="items-start gap-4 px-7 pt-7 text-left">
              <div className="flex size-11 items-center justify-center rounded-none bg-red-50 text-red-600">
                <TriangleAlert className="size-5" />
              </div>
              <div className="space-y-2">
                <AlertDialogTitle className="text-[22px] font-semibold leading-none text-zinc-900">
                  清空标记
                </AlertDialogTitle>
                <AlertDialogDescription className="text-[14px] leading-6 text-zinc-600">
                  确认清空当前图纸的全部笔记吗？清空后不可恢复。
                </AlertDialogDescription>
              </div>
            </AlertDialogHeader>
            <AlertDialogFooter className="mt-7 flex-row justify-end gap-3 border-t border-zinc-100 px-7 py-5">
              <AlertDialogCancel className="h-10 rounded-none border-border bg-white px-6 text-[15px] font-medium text-zinc-700 hover:bg-secondary">
                取消
              </AlertDialogCancel>
              <AlertDialogAction
                onClick={() => { void confirmClear(); }}
                className="h-10 rounded-none bg-red-600 px-6 text-[15px] font-semibold text-white hover:bg-red-700"
              >
                确认清空
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  );
}
