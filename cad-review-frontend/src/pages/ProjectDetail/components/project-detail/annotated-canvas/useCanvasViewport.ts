/**
 * 管理画布视口：stage 尺寸、缩放、平移、坐标转换。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { KonvaEventObject } from 'konva/lib/Node';
import type { ImageAsset, StageView, ViewMode } from './types';
import { clampZoom } from './constants';

interface UseCanvasViewportOptions {
  viewportRef: React.RefObject<HTMLDivElement | null>;
  stageRef: React.RefObject<import('konva/lib/Stage').Stage | null>;
  imageAsset: ImageAsset | null;
  imageStatus: 'loading' | 'ready' | 'error';
}

export function useCanvasViewport({
  viewportRef,
  stageRef,
  imageAsset,
  imageStatus,
}: UseCanvasViewportOptions) {
  const minZoomRef = useRef(0.05);
  const viewRef = useRef<StageView>({ x: 0, y: 0, scale: 1 });

  const [stageSize, setStageSize] = useState({ width: 1, height: 1 });
  const [view, setView] = useState<StageView>({ x: 0, y: 0, scale: 1 });
  const [zoomPercent, setZoomPercent] = useState(100);

  useEffect(() => {
    viewRef.current = view;
  }, [view]);

  const resetViewportToFit = useCallback((mode: ViewMode = 'default') => {
    if (!imageAsset) return;
    const width = Math.max(1, stageSize.width);
    const height = Math.max(1, stageSize.height);
    const imageWidth = imageAsset.width;
    const imageHeight = imageAsset.height;
    const targetBounds = mode === 'contain'
      ? { x: 0, y: 0, width: imageWidth, height: imageHeight }
      : imageAsset.contentBounds;

    const containZoom = Math.min(width / imageWidth, height / imageHeight);
    const targetZoom = Math.min(
      width / Math.max(1, targetBounds.width),
      height / Math.max(1, targetBounds.height),
    );
    const zoom = mode === 'contain' ? containZoom : targetZoom;
    minZoomRef.current = containZoom;

    const targetCenterX = targetBounds.x + targetBounds.width / 2;
    const targetCenterY = targetBounds.y + targetBounds.height / 2;
    const next = {
      x: width / 2 - targetCenterX * zoom,
      y: height / 2 - targetCenterY * zoom,
      scale: zoom,
    };
    setView(next);
    setZoomPercent(Math.round(zoom * 100));
  }, [imageAsset, stageSize.height, stageSize.width]);

  const toImagePoint = useCallback((point: { x: number; y: number }) => {
    const currentView = viewRef.current;
    const scale = currentView.scale || 1;
    return {
      x: (point.x - currentView.x) / scale,
      y: (point.y - currentView.y) / scale,
    };
  }, []);

  const getPointerInStage = useCallback((event: MouseEvent) => {
    const stage = stageRef.current;
    if (!stage) return null;
    const pointer = stage.getPointerPosition();
    if (pointer) return pointer;

    const container = stage.container();
    const rect = container.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }, [stageRef]);

  const handleWheel = useCallback((event: KonvaEventObject<WheelEvent>) => {
    event.evt.preventDefault();
    event.evt.stopPropagation();
    const stage = stageRef.current;
    if (!stage) return;
    const pointer = stage.getPointerPosition();
    if (!pointer) return;

    const currentView = viewRef.current;
    const minZoom = minZoomRef.current || 0.05;
    const nextZoom = clampZoom(currentView.scale * Math.exp(-event.evt.deltaY * 0.0015), minZoom);

    if (nextZoom <= minZoom + 1e-6) {
      resetViewportToFit('contain');
      return;
    }

    const mousePointTo = {
      x: (pointer.x - currentView.x) / currentView.scale,
      y: (pointer.y - currentView.y) / currentView.scale,
    };

    const next = {
      x: pointer.x - mousePointTo.x * nextZoom,
      y: pointer.y - mousePointTo.y * nextZoom,
      scale: nextZoom,
    };
    setView(next);
    setZoomPercent(Math.round(nextZoom * 100));
  }, [resetViewportToFit, stageRef]);

  const handleZoomByFactor = useCallback((factor: number) => {
    const currentView = viewRef.current;
    const minZoom = minZoomRef.current || 0.05;
    const nextZoom = clampZoom(currentView.scale * factor, minZoom);
    if (nextZoom <= minZoom + 1e-6) {
      resetViewportToFit('contain');
      return;
    }

    const next = {
      x: stageSize.width / 2 - ((stageSize.width / 2 - currentView.x) / currentView.scale) * nextZoom,
      y: stageSize.height / 2 - ((stageSize.height / 2 - currentView.y) / currentView.scale) * nextZoom,
      scale: nextZoom,
    };
    setView(next);
    setZoomPercent(Math.round(nextZoom * 100));
  }, [resetViewportToFit, stageSize.height, stageSize.width]);

  // 监听视口容器的尺寸变化 + 阻止原生滚动
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    const observer = new ResizeObserver(() => {
      const rect = viewport.getBoundingClientRect();
      setStageSize({
        width: Math.max(1, Math.floor(rect.width)),
        height: Math.max(1, Math.floor(rect.height)),
      });
    });
    observer.observe(viewport);

    const preventWheelScroll = (event: WheelEvent) => {
      event.preventDefault();
    };
    viewport.addEventListener('wheel', preventWheelScroll, { passive: false });

    return () => {
      observer.disconnect();
      viewport.removeEventListener('wheel', preventWheelScroll);
    };
  }, [viewportRef]);

  // 禁止右键菜单
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const container = stage.container();
    const preventContext = (event: MouseEvent) => event.preventDefault();
    container.addEventListener('contextmenu', preventContext);
    return () => container.removeEventListener('contextmenu', preventContext);
  }, [imageStatus, stageRef]);

  // 图片加载完成后自适应视口
  useEffect(() => {
    if (imageStatus !== 'ready' || !imageAsset) return;
    resetViewportToFit('default');
  }, [imageAsset, imageStatus, resetViewportToFit, stageSize.height, stageSize.width]);

  return {
    stageSize,
    view,
    setView,
    viewRef,
    zoomPercent,
    resetViewportToFit,
    toImagePoint,
    getPointerInStage,
    handleWheel,
    handleZoomByFactor,
  };
}
