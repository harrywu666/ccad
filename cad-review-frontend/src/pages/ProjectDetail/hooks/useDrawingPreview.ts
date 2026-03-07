import { useCallback, useEffect, useRef, useState, type MouseEvent, type WheelEvent } from 'react';

export interface PreviewDrawing {
  drawingId: string;
  dataVersion: number;
  sheetNo: string;
  sheetName: string;
  pageIndex: number | null;
  imageUrl: string;
}

const clampPreviewScale = (value: number) => Math.min(5, Math.max(0.3, value));
const normalizeWheelDelta = (event: WheelEvent<HTMLDivElement>) => {
  const baseDelta = event.deltaY;
  if (event.deltaMode === 1) return baseDelta * 16;
  if (event.deltaMode === 2) return baseDelta * window.innerHeight;
  return baseDelta;
};

interface UseDrawingPreviewOptions {
  lockPageOnOpen?: boolean;
  enableEscClose?: boolean;
}

export function useDrawingPreview(options: UseDrawingPreviewOptions = {}) {
  const { lockPageOnOpen = true, enableEscClose = true } = options;
  const [previewDrawing, setPreviewDrawing] = useState<PreviewDrawing | null>(null);
  const [previewScale, setPreviewScale] = useState(1);
  const [previewOffset, setPreviewOffset] = useState({ x: 0, y: 0 });
  const [isPreviewPanning, setIsPreviewPanning] = useState(false);
  const previewViewportRef = useRef<HTMLDivElement | null>(null);
  const panLastPointRef = useRef<{ x: number; y: number } | null>(null);

  const zoomPreview = useCallback((factor: number, originX = 0, originY = 0) => {
    setPreviewScale((prev) => {
      const next = clampPreviewScale(Number((prev * factor).toFixed(3)));
      if (next === prev) return prev;
      const ratio = next / prev;
      setPreviewOffset((offset) => ({
        x: offset.x - originX * (ratio - 1),
        y: offset.y - originY * (ratio - 1),
      }));
      return next;
    });
  }, []);

  const handlePreviewWheel = useCallback((event: WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const viewport = previewViewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();
    const originX = event.clientX - rect.left - rect.width / 2;
    const originY = event.clientY - rect.top - rect.height / 2;
    const normalizedDelta = Math.max(-120, Math.min(120, normalizeWheelDelta(event)));
    const factor = Math.exp(-normalizedDelta * 0.0015);
    zoomPreview(factor, originX, originY);
  }, [zoomPreview]);

  const handlePreviewMouseDown = useCallback((event: MouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    setIsPreviewPanning(true);
    panLastPointRef.current = { x: event.clientX, y: event.clientY };
  }, []);

  const resetPreview = useCallback(() => {
    setPreviewScale(1);
    setPreviewOffset({ x: 0, y: 0 });
    setIsPreviewPanning(false);
    panLastPointRef.current = null;
  }, []);

  useEffect(() => {
    if (!previewDrawing || !enableEscClose) return;
    const handleEscClose = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPreviewDrawing(null);
    };
    window.addEventListener('keydown', handleEscClose);
    return () => window.removeEventListener('keydown', handleEscClose);
  }, [enableEscClose, previewDrawing]);

  useEffect(() => {
    if (!isPreviewPanning) return;
    const onMouseMove = (event: globalThis.MouseEvent) => {
      if (!panLastPointRef.current) return;
      const dx = event.clientX - panLastPointRef.current.x;
      const dy = event.clientY - panLastPointRef.current.y;
      panLastPointRef.current = { x: event.clientX, y: event.clientY };
      setPreviewOffset((prev) => ({ x: prev.x + dx, y: prev.y + dy }));
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
    if (!previewDrawing || !lockPageOnOpen) return;
    const prevBodyOverflow = document.body.style.overflow;
    const prevHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prevBodyOverflow;
      document.documentElement.style.overflow = prevHtmlOverflow;
    };
  }, [lockPageOnOpen, previewDrawing]);

  return {
    previewDrawing,
    previewScale,
    previewOffset,
    isPreviewPanning,
    previewViewportRef,
    setPreviewDrawing,
    zoomPreview,
    handlePreviewWheel,
    handlePreviewMouseDown,
    resetPreview,
  };
}
