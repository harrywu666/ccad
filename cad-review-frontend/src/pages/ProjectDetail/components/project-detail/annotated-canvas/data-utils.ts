/**
 * DrawingAnnotationBoard ↔ AnnotationItem[] 双向转换函数。
 */

import type {
  AnnotationItem,
  DrawingAnnotationBoard,
  DrawingAnnotationObject,
  PreviewDrawing,
} from './types';
import { BRUSH_COLOR, DEFAULT_BRUSH_WIDTH, DEFAULT_TEXT_SIZE, MIN_BRUSH_WIDTH, MIN_TEXT_SIZE, makeId, normalizeText } from './constants';

export function buildEmptyBoard(previewDrawing: PreviewDrawing): DrawingAnnotationBoard {
  return {
    drawing_id: previewDrawing.drawingId,
    drawing_data_version: previewDrawing.dataVersion,
    schema_version: 1,
    objects: [],
  };
}

function parseLegacyPath(path: unknown): number[] {
  if (!Array.isArray(path)) return [];
  const points: number[] = [];
  path.forEach((command) => {
    if (!Array.isArray(command) || command.length < 3) return;
    const nums = command.slice(1).filter((item) => typeof item === 'number') as number[];
    if (nums.length >= 2) {
      points.push(nums[nums.length - 2], nums[nums.length - 1]);
    }
  });
  return points;
}

function parseStrokePoints(path: string): number[] {
  try {
    const parsed = JSON.parse(path);
    if (Array.isArray(parsed) && parsed.every((item) => typeof item === 'number')) {
      return parsed as number[];
    }
    if (
      parsed
      && typeof parsed === 'object'
      && (parsed as { kind?: string }).kind === 'points'
      && Array.isArray((parsed as { points?: unknown[] }).points)
    ) {
      const list = (parsed as { points: unknown[] }).points;
      if (list.every((item) => typeof item === 'number')) {
        return list as number[];
      }
    }
    return parseLegacyPath(parsed);
  } catch {
    return [];
  }
}

export function boardToItems(board: DrawingAnnotationBoard): AnnotationItem[] {
  const result: AnnotationItem[] = [];
  board.objects.forEach((object) => {
    if (object.type === 'stroke') {
      const points = parseStrokePoints(object.path || '');
      if (points.length >= 4) {
        result.push({
          id: makeId(),
          type: 'stroke',
          color: object.color || BRUSH_COLOR,
          strokeWidth: Math.max(MIN_BRUSH_WIDTH, object.stroke_width || DEFAULT_BRUSH_WIDTH),
          points,
        });
      }
      return;
    }

    const normalized = normalizeText(object.text || '');
    if (!normalized) return;
    result.push({
      id: makeId(),
      type: 'text',
      text: normalized,
      x: object.x ?? 0,
      y: object.y ?? 0,
      fontSize: Math.max(MIN_TEXT_SIZE, object.font_size || DEFAULT_TEXT_SIZE),
      color: object.color || BRUSH_COLOR,
    });
  });
  return result;
}

export function itemsToBoard(items: AnnotationItem[], drawing: PreviewDrawing): DrawingAnnotationBoard {
  const objects: DrawingAnnotationObject[] = items.map((item) => {
    if (item.type === 'stroke') {
      return {
        type: 'stroke' as const,
        color: item.color,
        stroke_width: item.strokeWidth,
        path: JSON.stringify({ kind: 'points', points: item.points }),
        x: 0,
        y: 0,
        scale_x: 1,
        scale_y: 1,
      };
    }
    return {
      type: 'text' as const,
      text: item.text,
      x: item.x,
      y: item.y,
      font_size: item.fontSize,
      color: item.color,
    };
  });

  return {
    drawing_id: drawing.drawingId,
    drawing_data_version: drawing.dataVersion,
    schema_version: 1,
    objects,
  };
}
