/**
 * 图片加载、缩放和内容边界检测的纯工具函数。
 */

import type { ContentBounds, ImageAsset } from './types';
import { CONTENT_SCAN_MAX_DIM } from './constants';

export function loadImageElement(url: string): Promise<HTMLImageElement> {
  const loadOnce = (src: string) => new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = 'anonymous';
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('图纸图片加载失败'));
    image.src = src;
  });

  const loadFromBlob = async (src: string) => {
    const response = await fetch(src, { mode: 'cors', cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`图纸图片加载失败（HTTP ${response.status}）`);
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    try {
      return await loadOnce(objectUrl);
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  };

  if (!url) {
    return Promise.reject(new Error('图纸图片 URL 为空'));
  }

  return loadOnce(url).catch(() => {
    const retryUrl = `${url}${url.includes('?') ? '&' : '?'}_t=${Date.now()}`;
    return loadOnce(retryUrl).catch(() => loadFromBlob(retryUrl));
  });
}

export function getImageDimensions(image: HTMLImageElement): { width: number; height: number } {
  return {
    width: image.naturalWidth || image.width || 1,
    height: image.naturalHeight || image.height || 1,
  };
}

export function createRenderSource(image: HTMLImageElement): HTMLImageElement {
  return image;
}

export function detectContentBounds(
  source: HTMLImageElement,
  width: number,
  height: number,
): ContentBounds {
  const full: ContentBounds = { x: 0, y: 0, width, height };
  const maxDimension = Math.max(width, height);
  if (maxDimension <= 0) return full;

  const scanScale = Math.min(1, CONTENT_SCAN_MAX_DIM / maxDimension);
  const scanWidth = Math.max(1, Math.round(width * scanScale));
  const scanHeight = Math.max(1, Math.round(height * scanScale));
  const canvas = document.createElement('canvas');
  canvas.width = scanWidth;
  canvas.height = scanHeight;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) return full;

  context.drawImage(source, 0, 0, scanWidth, scanHeight);

  try {
    const data = context.getImageData(0, 0, scanWidth, scanHeight).data;
    let minX = scanWidth;
    let minY = scanHeight;
    let maxX = -1;
    let maxY = -1;
    let hits = 0;
    const alphaThreshold = 8;
    const whiteThreshold = 246;

    for (let y = 0; y < scanHeight; y += 1) {
      for (let x = 0; x < scanWidth; x += 1) {
        const index = (y * scanWidth + x) * 4;
        const alpha = data[index + 3];
        if (alpha < alphaThreshold) continue;
        const red = data[index];
        const green = data[index + 1];
        const blue = data[index + 2];
        if (red >= whiteThreshold && green >= whiteThreshold && blue >= whiteThreshold) continue;
        hits += 1;
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
      }
    }

    if (!hits || maxX <= minX || maxY <= minY) {
      return full;
    }

    const pad = 4;
    const scaledX = (Math.max(0, minX - pad)) / scanScale;
    const scaledY = (Math.max(0, minY - pad)) / scanScale;
    const scaledW = (Math.min(scanWidth - 1, maxX + pad) - Math.max(0, minX - pad) + 1) / scanScale;
    const scaledH = (Math.min(scanHeight - 1, maxY + pad) - Math.max(0, minY - pad) + 1) / scanScale;

    const clampedWidth = Math.max(1, Math.min(width, scaledW));
    const clampedHeight = Math.max(1, Math.min(height, scaledH));
    const clampedX = Math.max(0, Math.min(width - clampedWidth, scaledX));
    const clampedY = Math.max(0, Math.min(height - clampedHeight, scaledY));

    return {
      x: clampedX,
      y: clampedY,
      width: clampedWidth,
      height: clampedHeight,
    };
  } catch {
    return full;
  }
}

export function buildImageAsset(image: HTMLImageElement): ImageAsset {
  const dimensions = getImageDimensions(image);
  const source = createRenderSource(image);
  const contentBounds = detectContentBounds(source, dimensions.width, dimensions.height);
  return {
    source,
    width: dimensions.width,
    height: dimensions.height,
    contentBounds,
  };
}
