/**
 * 管理标注数据的加载、保存、撤销和清空。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '@/api';
import type { AnnotationItem, DrawingAnnotationBoard, ImageAsset, PreviewDrawing, SaveState } from './types';
import { SAVE_DEBOUNCE_MS } from './constants';
import { buildImageAsset, loadImageElement } from './image-utils';
import { boardToItems, buildEmptyBoard, itemsToBoard } from './data-utils';

interface UseAnnotationBoardOptions {
  projectId: string;
  previewDrawing: PreviewDrawing;
  auditVersion: number;
}

export function useAnnotationBoard({ projectId, previewDrawing, auditVersion }: UseAnnotationBoardOptions) {
  const loadRequestRef = useRef(0);
  const saveTimerRef = useRef<number | null>(null);
  const pendingBoardRef = useRef<DrawingAnnotationBoard | null>(null);
  const currentDrawingIdRef = useRef(previewDrawing.drawingId);
  const itemsRef = useRef<AnnotationItem[]>([]);
  const historyRef = useRef<string[]>([]);

  const [imageStatus, setImageStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [imageAsset, setImageAsset] = useState<ImageAsset | null>(null);
  const [saveState, setSaveState] = useState<SaveState>('loading');
  const [loadErrorMessage, setLoadErrorMessage] = useState('');
  const [items, setItems] = useState<AnnotationItem[]>([]);
  const [historyDepth, setHistoryDepth] = useState(0);

  currentDrawingIdRef.current = previewDrawing.drawingId;

  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  const syncItems = useCallback((nextItems: AnnotationItem[]) => {
    itemsRef.current = nextItems;
    setItems(nextItems);
  }, []);

  const saveBoard = useCallback(async (board: DrawingAnnotationBoard) => {
    pendingBoardRef.current = null;
    if (currentDrawingIdRef.current === board.drawing_id) {
      setSaveState('saving');
    }

    try {
      await api.saveDrawingAnnotations(projectId, board.drawing_id, auditVersion, {
        drawing_data_version: board.drawing_data_version,
        schema_version: board.schema_version,
        objects: board.objects,
      });
      if (currentDrawingIdRef.current === board.drawing_id) {
        setSaveState('saved');
      }
    } catch (error) {
      console.error('保存图纸标注失败', error);
      if (currentDrawingIdRef.current === board.drawing_id) {
        setSaveState('error');
      }
    }
  }, [projectId, auditVersion]);

  const flushPendingSave = useCallback(() => {
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    const board = pendingBoardRef.current;
    if (board) {
      pendingBoardRef.current = null;
      void saveBoard(board);
    }
  }, [saveBoard]);

  const scheduleSave = useCallback((nextItems: AnnotationItem[]) => {
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
    }
    const board = itemsToBoard(nextItems, previewDrawing);
    pendingBoardRef.current = board;
    saveTimerRef.current = window.setTimeout(() => {
      void saveBoard(board);
    }, SAVE_DEBOUNCE_MS);
  }, [previewDrawing, saveBoard]);

  const commitItemsChange = useCallback((nextItems: AnnotationItem[]) => {
    syncItems(nextItems);
    const snapshot = JSON.stringify(nextItems);
    const lastSnapshot = historyRef.current[historyRef.current.length - 1];
    if (snapshot !== lastSnapshot) {
      historyRef.current.push(snapshot);
      if (historyRef.current.length > 100) historyRef.current.shift();
      setHistoryDepth(historyRef.current.length);
    }
    scheduleSave(nextItems);
  }, [scheduleSave, syncItems]);

  const handleUndo = useCallback(() => {
    if (historyRef.current.length <= 1) return;
    historyRef.current.pop();
    setHistoryDepth(historyRef.current.length);
    const previous = historyRef.current[historyRef.current.length - 1];
    if (!previous) return;
    const restored = JSON.parse(previous) as AnnotationItem[];
    syncItems(restored);
    scheduleSave(restored);
  }, [scheduleSave, syncItems]);

  const clearBoard = useCallback(async () => {
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    pendingBoardRef.current = null;

    syncItems([]);
    historyRef.current = [JSON.stringify([])];
    setHistoryDepth(historyRef.current.length);
    setSaveState('saving');

    try {
      await api.clearDrawingAnnotations(projectId, previewDrawing.drawingId, auditVersion);
      setSaveState('saved');
    } catch (error) {
      console.error('清空图纸标注失败', error);
      setSaveState('error');
    }
  }, [projectId, previewDrawing.drawingId, auditVersion, syncItems]);

  // 切换图纸时加载图片和标注数据
  useEffect(() => {
    let cancelled = false;
    const requestId = loadRequestRef.current + 1;
    loadRequestRef.current = requestId;

    flushPendingSave();

    setImageStatus('loading');
    setSaveState('loading');
    setLoadErrorMessage('');
    setImageAsset(null);
    syncItems([]);
    historyRef.current = [];
    setHistoryDepth(0);

    const load = async () => {
      try {
        const [image, board] = await Promise.all([
          loadImageElement(previewDrawing.imageUrl),
          api.getDrawingAnnotations(projectId, previewDrawing.drawingId, auditVersion)
            .catch(() => buildEmptyBoard(previewDrawing)),
        ]);

        if (cancelled || requestId !== loadRequestRef.current) return;

        const nextItems = boardToItems(board);
        const nextAsset = buildImageAsset(image);
        setImageAsset(nextAsset);
        syncItems(nextItems);
        historyRef.current = [JSON.stringify(nextItems)];
        setHistoryDepth(historyRef.current.length);
        setImageStatus('ready');
        setSaveState('idle');
      } catch (error) {
        console.error('加载图纸失败', error);
        if (cancelled || requestId !== loadRequestRef.current) return;
        setLoadErrorMessage(error instanceof Error ? error.message : '未知错误');
        setImageStatus('error');
        setSaveState('error');
      }
    };

    void load();

    return () => {
      cancelled = true;
      flushPendingSave();
    };
  }, [projectId, previewDrawing, syncItems, flushPendingSave]);

  // Ctrl+Z 全局撤销
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() !== 'z') return;
      if (event.defaultPrevented) return;

      const target = event.target as HTMLElement | null;
      if (
        target
        && (
          target.tagName === 'INPUT'
          || target.tagName === 'TEXTAREA'
          || target.isContentEditable
        )
      ) {
        return;
      }

      event.preventDefault();
      handleUndo();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [handleUndo]);

  return {
    imageStatus,
    imageAsset,
    saveState,
    loadErrorMessage,
    items,
    historyDepth,
    itemsRef,
    syncItems,
    commitItemsChange,
    handleUndo,
    clearBoard,
    scheduleSave,
  };
}
