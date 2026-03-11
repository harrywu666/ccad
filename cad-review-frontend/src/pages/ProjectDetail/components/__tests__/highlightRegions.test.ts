import { describe, expect, it } from 'vitest';
import { fallbackHighlightRegionFromPoint, toCanvasCloudHighlight } from '../project-detail/annotated-canvas/highlightRegions';
import type { ImageAsset } from '../project-detail/annotated-canvas/types';

const imageAsset = {
  width: 1000,
  height: 800,
} as ImageAsset;

describe('highlightRegions', () => {
  it('把点坐标补成小云线框', () => {
    expect(fallbackHighlightRegionFromPoint({ x: 50, y: 50 })).toEqual({
      x: 47.9,
      y: 47.9,
      width: 4.2,
      height: 4.2,
    });
  });

  it('额外问题只有点位时也统一转成云线框', () => {
    expect(toCanvasCloudHighlight({
      imageAsset,
      key: 'extra-1',
      point: { x: 20, y: 30 },
      variant: 'exact',
      label: '索引A2',
    })).toEqual({
      key: 'extra-1',
      x: 179,
      y: 223.2,
      width: 42,
      height: 33.6,
      variant: 'exact',
      label: '索引A2',
    });
  });

  it('有明确定位框时直接用定位框，不退回圆点', () => {
    expect(toCanvasCloudHighlight({
      imageAsset,
      key: 'primary',
      point: { x: 10, y: 10 },
      region: {
        bbox_pct: { x: 40, y: 25, width: 6, height: 8 },
      },
      variant: 'exact',
    })).toEqual({
      key: 'primary',
      x: 400,
      y: 200,
      width: 60,
      height: 64,
      variant: 'exact',
      label: undefined,
    });
  });
});
