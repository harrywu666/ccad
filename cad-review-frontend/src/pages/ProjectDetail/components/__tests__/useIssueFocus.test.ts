import { describe, expect, it } from 'vitest';
import { computeIssueFocusView } from '../project-detail/annotated-canvas/useIssueFocus';
import type { ImageAsset } from '../project-detail/annotated-canvas/types';

const imageAsset = {
  width: 2000,
  height: 1200,
} as ImageAsset;

describe('computeIssueFocusView', () => {
  it('低置信度黄框也会自动聚焦', () => {
    const result = computeIssueFocusView({
      drawingId: 'drawing-1',
      focusAnchorStatus: 'pdf_low_confidence',
      focusAnchor: {
        role: 'source',
        sheet_no: 'A1.00',
        global_pct: { x: 40, y: 60 },
        confidence: 0.42,
      },
      focusHighlightRegion: {
        shape: 'cloud_rect',
        bbox_pct: { x: 35, y: 55, width: 6, height: 8 },
      },
      imageAsset,
      imageStatus: 'ready',
      stageSize: { width: 1000, height: 700 },
    });

    expect(result).not.toBeNull();
    expect(result?.view.scale).toBeGreaterThan(0.95);
  });

  it('新的区域聚焦倍率会比旧逻辑更收一点', () => {
    const result = computeIssueFocusView({
      drawingId: 'drawing-2',
      focusAnchorStatus: 'pdf_ready',
      focusAnchor: {
        role: 'source',
        sheet_no: 'A1.00',
        global_pct: { x: 50, y: 50 },
        confidence: 0.98,
      },
      focusHighlightRegion: {
        shape: 'cloud_rect',
        bbox_pct: { x: 40, y: 40, width: 10, height: 10 },
      },
      imageAsset,
      imageStatus: 'ready',
      stageSize: { width: 1000, height: 700 },
    });

    expect(result).not.toBeNull();
    expect(result?.view.scale).toBeLessThanOrEqual(1.4);
  });
});
