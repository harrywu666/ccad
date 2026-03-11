import { useEffect, useRef } from 'react';
import type { IssueFocusAnchor, IssueHighlightRegion } from '@/types';
import type { ImageAsset, StageView } from './types';

interface UseIssueFocusOptions {
  drawingId: string;
  focusAnchor?: IssueFocusAnchor | null;
  focusHighlightRegion?: IssueHighlightRegion | null;
  focusAnchorStatus?: 'pdf_ready' | 'pdf_low_confidence' | 'pdf_visual_mismatch' | 'layout_fallback' | 'layout_only' | 'missing' | null;
  imageAsset: ImageAsset | null;
  imageStatus: 'loading' | 'ready' | 'error';
  stageSize: { width: number; height: number };
  setView: React.Dispatch<React.SetStateAction<StageView>>;
}

interface ComputeIssueFocusViewParams {
  drawingId: string;
  focusAnchor?: IssueFocusAnchor | null;
  focusHighlightRegion?: IssueHighlightRegion | null;
  focusAnchorStatus?: 'pdf_ready' | 'pdf_low_confidence' | 'pdf_visual_mismatch' | 'layout_fallback' | 'layout_only' | 'missing' | null;
  imageAsset: ImageAsset | null;
  imageStatus: 'loading' | 'ready' | 'error';
  stageSize: { width: number; height: number };
}

interface ComputedIssueFocusView {
  key: string;
  view: StageView;
}

export function computeIssueFocusView({
  drawingId,
  focusAnchor,
  focusHighlightRegion,
  focusAnchorStatus,
  imageAsset,
  imageStatus,
  stageSize,
}: ComputeIssueFocusViewParams): ComputedIssueFocusView | null {
  if (imageStatus !== 'ready' || !imageAsset) return null;
  if (focusAnchorStatus === 'pdf_visual_mismatch') return null;

  const region = focusHighlightRegion?.bbox_pct;
  const hasRegion = (
    region
    && typeof region.x === 'number'
    && typeof region.y === 'number'
    && typeof region.width === 'number'
    && typeof region.height === 'number'
    && region.width > 0
    && region.height > 0
  );
  const point = focusAnchor?.global_pct;
  const hasPoint = point && typeof point.x === 'number' && typeof point.y === 'number';
  if (!hasRegion && !hasPoint) return null;
  if (!hasRegion && typeof focusAnchor?.confidence === 'number' && focusAnchor.confidence < 0.6 && focusAnchorStatus !== 'pdf_low_confidence') {
    return null;
  }

  let anchorX = 0;
  let anchorY = 0;
  let focusScale = 1.2;
  let key = drawingId;

  if (hasRegion && region) {
    const boxX = imageAsset.width * (region.x / 100);
    const boxY = imageAsset.height * (region.y / 100);
    const boxWidth = imageAsset.width * (region.width / 100);
    const boxHeight = imageAsset.height * (region.height / 100);
    anchorX = boxX + boxWidth / 2;
    anchorY = boxY + boxHeight / 2;
    const paddedWidth = Math.max(boxWidth * 4.2, 240);
    const paddedHeight = Math.max(boxHeight * 4.2, 240);
    focusScale = Math.min(
      2.1,
      Math.max(
        0.95,
        Math.min(
          stageSize.width / Math.max(paddedWidth, 1),
          stageSize.height / Math.max(paddedHeight, 1),
        ),
      ),
    );
    key = `${drawingId}:region:${region.x}:${region.y}:${region.width}:${region.height}:${stageSize.width}:${stageSize.height}`;
  } else if (hasPoint && point) {
    anchorX = imageAsset.width * (point.x / 100);
    anchorY = imageAsset.height * (point.y / 100);
    focusScale = Math.min(
      1.8,
      Math.max(
        0.95,
        Math.min(
          stageSize.width / Math.max(imageAsset.width * 0.42, 1),
          stageSize.height / Math.max(imageAsset.height * 0.42, 1),
        ),
      ),
    );
    key = `${drawingId}:point:${point.x}:${point.y}:${stageSize.width}:${stageSize.height}`;
  }

  return {
    key,
    view: {
      x: stageSize.width / 2 - anchorX * focusScale,
      y: stageSize.height / 2 - anchorY * focusScale,
      scale: focusScale,
    },
  };
}

export function useIssueFocus({
  drawingId,
  focusAnchor,
  focusHighlightRegion,
  focusAnchorStatus,
  imageAsset,
  imageStatus,
  stageSize,
  setView,
}: UseIssueFocusOptions) {
  const appliedKeyRef = useRef('');

  useEffect(() => {
    appliedKeyRef.current = '';
  }, [drawingId]);

  useEffect(() => {
    const nextFocus = computeIssueFocusView({
      drawingId,
      focusAnchor,
      focusHighlightRegion,
      focusAnchorStatus,
      imageAsset,
      imageStatus,
      stageSize,
    });
    if (!nextFocus) return;
    if (appliedKeyRef.current === nextFocus.key) return;
    appliedKeyRef.current = nextFocus.key;
    setView(nextFocus.view);
  }, [drawingId, focusAnchor, focusHighlightRegion, focusAnchorStatus, imageAsset, imageStatus, setView, stageSize.height, stageSize.width]);
}
