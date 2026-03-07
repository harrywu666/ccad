/**
 * AnnotatedDrawingPreviewCanvas 使用的常量和小型工具函数。
 */

export const BRUSH_COLOR = '#ff3b30';
export const SAVE_DEBOUNCE_MS = 800;
export const MAX_ZOOM = 5;
export const CONTENT_SCAN_MAX_DIM = 512;
export const MIN_BRUSH_WIDTH = 12;
export const MIN_TEXT_SIZE = 100;
export const MAX_TEXT_SIZE = 1200;
export const BRUSH_WIDTH_OPTIONS = [12, 16, 20, 28, 36] as const;
export const TEXT_SIZE_OPTIONS = [100, 120, 160, 220, 300] as const;
export const DEFAULT_BRUSH_WIDTH = 20;
export const DEFAULT_TEXT_SIZE = 100;

export function makeId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function clampZoom(value: number, minZoom: number): number {
  return Math.min(MAX_ZOOM, Math.max(minZoom, value));
}

export function normalizeText(value: string): string {
  return value.replace(/\s*\n+\s*/g, ' ').trim();
}
