import type { ImageAsset } from './types';

const FALLBACK_HIGHLIGHT_SIDE_PCT = 4.2;

type PctPoint = { x: number; y: number };
type PctBox = { x: number; y: number; width: number; height: number };

export interface CanvasCloudHighlight {
  key: string;
  x: number;
  y: number;
  width: number;
  height: number;
  variant: 'exact' | 'estimated';
  label?: string;
}

const isPctPoint = (value: unknown): value is PctPoint => (
  !!value
  && typeof value === 'object'
  && typeof (value as PctPoint).x === 'number'
  && typeof (value as PctPoint).y === 'number'
);

const isPctBox = (value: unknown): value is PctBox => (
  !!value
  && typeof value === 'object'
  && typeof (value as PctBox).x === 'number'
  && typeof (value as PctBox).y === 'number'
  && typeof (value as PctBox).width === 'number'
  && typeof (value as PctBox).height === 'number'
  && (value as PctBox).width > 0
  && (value as PctBox).height > 0
);

export function fallbackHighlightRegionFromPoint(point: PctPoint): PctBox {
  const side = FALLBACK_HIGHLIGHT_SIDE_PCT;
  return {
    x: Math.max(0, Math.min(100 - side, point.x - side / 2)),
    y: Math.max(0, Math.min(100 - side, point.y - side / 2)),
    width: side,
    height: side,
  };
}

export function toCanvasCloudHighlight(params: {
  imageAsset: ImageAsset | null;
  key: string;
  point?: PctPoint | null;
  region?: { bbox_pct?: PctBox | null } | null;
  variant?: 'exact' | 'estimated';
  label?: string;
}): CanvasCloudHighlight | null {
  const { imageAsset, key, point, region, variant = 'exact', label } = params;
  if (!imageAsset) return null;

  const bbox = isPctBox(region?.bbox_pct)
    ? region!.bbox_pct!
    : (isPctPoint(point) ? fallbackHighlightRegionFromPoint(point) : null);

  if (!bbox) return null;

  return {
    key,
    x: imageAsset.width * (bbox.x / 100),
    y: imageAsset.height * (bbox.y / 100),
    width: imageAsset.width * (bbox.width / 100),
    height: imageAsset.height * (bbox.height / 100),
    variant,
    label,
  };
}
