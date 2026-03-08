/**
 * AnnotatedDrawingPreviewCanvas 相关类型定义。
 */

import type { PreviewDrawing } from '../../../hooks/useDrawingPreview';

export type { PreviewDrawing };

export type ToolMode = 'pan' | 'draw' | 'text';
export type SaveState = 'loading' | 'idle' | 'saving' | 'saved' | 'error';
export type ViewMode = 'default' | 'contain';

export interface AnnotatedDrawingPreviewCanvasProps {
  projectId: string;
  previewDrawing: PreviewDrawing;
  auditVersion: number;
  availableVersions: number[];
  overlayVersions: number[];
  onToggleOverlayVersion: (version: number) => void;
}

export interface StageView {
  x: number;
  y: number;
  scale: number;
}

export interface ContentBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ImageAsset {
  source: HTMLImageElement;
  width: number;
  height: number;
  contentBounds: ContentBounds;
}

export interface StrokeAnnotationItem {
  id: string;
  type: 'stroke';
  color: string;
  strokeWidth: number;
  points: number[];
}

export interface TextAnnotationItem {
  id: string;
  type: 'text';
  text: string;
  x: number;
  y: number;
  fontSize: number;
  color: string;
}

export type AnnotationItem = StrokeAnnotationItem | TextAnnotationItem;

export interface DrawingAnnotationObject {
  type: 'stroke' | 'text';
  color?: string;
  stroke_width?: number;
  path?: string;
  text?: string;
  x?: number;
  y?: number;
  font_size?: number;
  scale_x?: number;
  scale_y?: number;
}

export interface DrawingAnnotationBoard {
  drawing_id: string;
  drawing_data_version: number;
  schema_version: number;
  objects: DrawingAnnotationObject[];
}
