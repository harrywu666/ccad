/**
 * 加载其他审图版本的标注数据，作为只读叠加层显示。
 * 按图号（sheetNo）匹配，而非 drawingId，因为不同版本可能重新上传图纸导致 drawingId 不同。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '@/api';
import type { AnnotationItem } from './types';
import { boardToItems } from './data-utils';

const OVERLAY_COLOR = '#3b82f6';

function recolorItems(items: AnnotationItem[]): AnnotationItem[] {
  return items.map((item) => ({ ...item, color: OVERLAY_COLOR }));
}

interface UseOverlayAnnotationsOptions {
  projectId: string;
  sheetNo: string;
  overlayVersions: number[];
}

export interface OverlayLayer {
  version: number;
  items: AnnotationItem[];
}

export function useOverlayAnnotations({
  projectId,
  sheetNo,
  overlayVersions,
}: UseOverlayAnnotationsOptions): OverlayLayer[] {
  const [layers, setLayers] = useState<OverlayLayer[]>([]);
  const cacheRef = useRef<Record<string, AnnotationItem[]>>({});

  const loadVersion = useCallback(async (version: number): Promise<AnnotationItem[]> => {
    const key = `${sheetNo}:${version}`;
    const cached = cacheRef.current[key];
    if (cached) return cached;

    try {
      const board = await api.getAnnotationsBySheet(projectId, sheetNo, version);
      const items = recolorItems(boardToItems(board));
      cacheRef.current[key] = items;
      return items;
    } catch {
      return [];
    }
  }, [projectId, sheetNo]);

  useEffect(() => {
    if (overlayVersions.length === 0) {
      setLayers([]);
      return;
    }

    let cancelled = false;

    const load = async () => {
      const results = await Promise.all(
        overlayVersions.map(async (version) => ({
          version,
          items: await loadVersion(version),
        })),
      );
      if (!cancelled) {
        setLayers(results.filter((layer) => layer.items.length > 0));
      }
    };

    void load();

    return () => { cancelled = true; };
  }, [overlayVersions, loadVersion]);

  useEffect(() => {
    cacheRef.current = {};
    setLayers([]);
  }, [sheetNo]);

  return layers;
}
