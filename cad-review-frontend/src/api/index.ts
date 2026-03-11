/// <reference types="vite/client" />
import axios from 'axios';
import type { AxiosProgressEvent } from 'axios';
import type {
  Category,
  Project,
  ProjectCreate,
  CatalogItem,
  Drawing,
  JsonData,
  AuditResult,
  AuditStatus,
  AuditFeedbackStatus,
  ThreeLineMatch,
  AuditResultPreview,
} from '@/types';
import type {
  AuditEventsResponse,
  AuditProviderMode,
  AuditRuntimeSummaryResponse,
  FeedbackAgentPromptAssetsResponse,
  FeedbackThread,
  FeedbackThreadMessage,
  SkillPackItem,
  SkillPackListResponse,
  SkillTypesResponse,
} from '@/types/api';

const API_BASE = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:7002').replace(/\/$/, '');

const api = axios.create({
  baseURL: API_BASE,
  timeout: 300000,
});

const buildUploadProgressHandler = (onUploadProgress?: (percent: number) => void) => {
  if (!onUploadProgress) return undefined;
  return (event: AxiosProgressEvent) => {
    if (!event.total || event.total <= 0) return;
    const percent = Math.max(0, Math.min(100, Math.round((event.loaded / event.total) * 100)));
    onUploadProgress(percent);
  };
};

// Categories
export const getCategories = () => api.get<Category[]>('/api/categories').then(res => res.data);
export const createCategory = (data: { name: string; color: string }) =>
  api.post<Category>('/api/categories', data).then(res => res.data);
export const updateCategory = (id: string, data: { name?: string; color?: string }) =>
  api.put<Category>(`/api/categories/${id}`, data).then(res => res.data);
export const deleteCategory = (id: string) => api.delete(`/api/categories/${id}`);

// Projects
export const getProjects = (params?: { category?: string; status?: string; search?: string }) =>
  api.get<Project[]>('/api/projects', { params }).then(res => res.data);
export const getProject = (id: string) => api.get<Project>(`/api/projects/${id}`).then(res => res.data);
export const createProject = (data: ProjectCreate) =>
  api.post<Project>('/api/projects', data).then(res => res.data);
export const updateProject = (id: string, data: Partial<ProjectCreate>) =>
  api.put<Project>(`/api/projects/${id}`, data).then(res => res.data);
export const deleteProject = (id: string) => api.delete(`/api/projects/${id}`);
export const getCacheVersion = (id: string, clientVersion: number = 0) =>
  api.get<{ cache_version: number; client_version: number; needs_refresh: boolean }>(
    `/api/projects/${id}/cache_version`, { params: { client_version: clientVersion } }
  ).then(res => res.data);
export const getProjectUiPreferences = (id: string) =>
  api.get<{ project_id: string; preferences: Record<string, any> }>(`/api/projects/${id}/ui-preferences`).then(res => res.data);
export const updateProjectUiPreferences = (id: string, preferences: Record<string, any>) =>
  api.put<{ project_id: string; preferences: Record<string, any> }>(`/api/projects/${id}/ui-preferences`, { preferences }).then(res => res.data);
export const getAIPromptSettings = () =>
  api.get<{ stages: any[] }>('/api/settings/ai-prompts').then(res => res.data);
export const updateAIPromptSettings = (
  stages: Array<{ stage_key: string; system_prompt: string; user_prompt: string }>,
) =>
  api.put<{ success: boolean }>('/api/settings/ai-prompts', { stages }).then(res => res.data);
export const resetAIPromptStage = (stageKey: string) =>
  api.post<{ success: boolean }>(`/api/settings/ai-prompts/${stageKey}/reset`).then(res => res.data);
export const getSkillTypes = () =>
  api.get<SkillTypesResponse>('/api/settings/skill-types').then(res => res.data);
export const getSkillPacks = (skillType?: string) =>
  api.get<SkillPackListResponse>('/api/settings/skill-packs', {
    params: skillType ? { skill_type: skillType } : undefined,
  }).then(res => res.data);
export const createSkillPack = (payload: {
  skill_type: string;
  title: string;
  content: string;
  priority?: number;
  stage_keys?: string[];
}) =>
  api.post<{ item: SkillPackItem }>('/api/settings/skill-packs', payload).then(res => res.data);
export const updateSkillPack = (
  id: string,
  payload: {
    title?: string;
    content?: string;
    priority?: number;
    stage_keys?: string[];
  },
) => api.put<{ item: SkillPackItem }>(`/api/settings/skill-packs/${id}`, payload).then(res => res.data);
export const deleteSkillPack = (id: string) =>
  api.delete<{ success: boolean }>(`/api/settings/skill-packs/${id}`).then(res => res.data);
export const toggleSkillPack = (id: string, isActive: boolean) =>
  api.post<{ item: SkillPackItem }>(`/api/settings/skill-packs/${id}/toggle`, {
    is_active: isActive,
  }).then(res => res.data);
export const generateSkillPacks = (skillType: string) =>
  api.post<{ items: SkillPackItem[]; generated: number }>('/api/settings/skill-packs/generate', {
    skill_type: skillType,
  }).then(res => res.data);
export const getAuditRuntimeSummaries = (limit = 10) =>
  api.get<AuditRuntimeSummaryResponse>('/api/settings/audit-runtime-summaries', {
    params: { limit },
  }).then(res => res.data);
export const getFeedbackAgentPromptAssets = () =>
  api.get<FeedbackAgentPromptAssetsResponse>('/api/settings/feedback-agent-prompts').then(res => res.data);
export const updateFeedbackAgentPromptAssets = (
  items: Array<{ key: 'prompt' | 'agent' | 'soul'; content: string }>,
) =>
  api.put<FeedbackAgentPromptAssetsResponse>('/api/settings/feedback-agent-prompts', { items }).then(res => res.data);

// Catalog
export const getCatalog = (projectId: string) =>
  api.get<CatalogItem[]>(`/api/projects/${projectId}/catalog`).then(res => res.data);
export const uploadCatalog = (projectId: string, file: File, options?: { onUploadProgress?: (percent: number) => void }) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post<{ success: boolean; items: any[] }>(
    `/api/projects/${projectId}/catalog/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: buildUploadProgressHandler(options?.onUploadProgress),
  }
  ).then(res => res.data);
};
export const updateCatalog = (projectId: string, items: any[]) =>
  api.put<CatalogItem[]>(`/api/projects/${projectId}/catalog`, { items }).then(res => res.data);
export const lockCatalog = (projectId: string) =>
  api.post<{ success: boolean }>(`/api/projects/${projectId}/catalog/lock`).then(res => res.data);
export const deleteCatalog = (projectId: string) =>
  api.delete(`/api/projects/${projectId}/catalog`);

// Drawings
export const getDrawings = (projectId: string) =>
  api.get<Drawing[]>(`/api/projects/${projectId}/drawings`).then(res => res.data);
export const uploadDrawings = (projectId: string, file: File, options?: { onUploadProgress?: (percent: number) => void }) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post<{ success: boolean; total: number; matched: number; unmatched: number }>(
    `/api/projects/${projectId}/drawings/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: buildUploadProgressHandler(options?.onUploadProgress),
  }
  ).then(res => res.data);
};
export const uploadDrawingsPng = (projectId: string, files: File[]) => {
  const formData = new FormData();
  files.forEach(file => formData.append('files', file));
  return api.post<{ success: boolean; total: number; matched: number; unmatched: number }>(
    `/api/projects/${projectId}/drawings/upload-png`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 600000,
  }).then(res => res.data);
};
export const getDrawingsUploadProgress = (projectId: string) =>
  api.get<{ phase: string; progress: number; message: string; success?: boolean }>(
    `/api/projects/${projectId}/drawings/upload-progress`
  ).then(res => res.data);
export const updateDrawing = (
  projectId: string,
  drawingId: string,
  data: { catalog_id?: string; sheet_no?: string; sheet_name?: string }
) =>
  api.put<{ success: boolean }>(`/api/projects/${projectId}/drawings/${drawingId}`, data)
    .then(res => res.data);
export const deleteDrawing = (projectId: string, drawingId: string) =>
  api.delete<{ success: boolean }>(`/api/projects/${projectId}/drawings/${drawingId}`).then(res => res.data);
export const batchDeleteDrawings = (projectId: string, drawingIds: string[]) =>
  api.post<{ success: boolean; deleted: number }>(`/api/projects/${projectId}/drawings/batch-delete`, { drawing_ids: drawingIds }).then(res => res.data);
export const deleteDrawings = (projectId: string) =>
  api.delete(`/api/projects/${projectId}/drawings`);
export const getDrawingAnnotations = (projectId: string, drawingId: string, auditVersion: number) =>
  api.get<any>(`/api/projects/${projectId}/drawings/${drawingId}/annotations`, { params: { audit_version: auditVersion } }).then(res => res.data);
export const saveDrawingAnnotations = (
  projectId: string,
  drawingId: string,
  auditVersion: number,
  payload: {
    drawing_data_version: number;
    schema_version: number;
    objects: any[];
  },
) =>
  api.put<any>(`/api/projects/${projectId}/drawings/${drawingId}/annotations`, payload, { params: { audit_version: auditVersion } }).then(res => res.data);
export const clearDrawingAnnotations = (projectId: string, drawingId: string, auditVersion: number) =>
  api.delete<any>(`/api/projects/${projectId}/drawings/${drawingId}/annotations`, { params: { audit_version: auditVersion } }).then(res => res.data);
export const getAnnotationsBySheet = (projectId: string, sheetNo: string, auditVersion: number) =>
  api.get<any>(`/api/projects/${projectId}/annotations-by-sheet`, { params: { sheet_no: sheetNo, audit_version: auditVersion } }).then(res => res.data);

// DWG
export const getJsonDataList = (projectId: string) =>
  api.get<JsonData[]>(`/api/projects/${projectId}/dwg`).then(res => res.data);
export const uploadDwg = (projectId: string, files: File[], options?: { onUploadProgress?: (percent: number) => void }) => {
  const formData = new FormData();
  files.forEach(f => formData.append('files', f));
  return api.post<{ success: boolean; results: any[] }>(
    `/api/projects/${projectId}/dwg/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: buildUploadProgressHandler(options?.onUploadProgress),
  }
  ).then(res => res.data);
};
export const getDwgUploadProgress = (projectId: string) =>
  api.get<{ phase: string; progress: number; message: string; success?: boolean }>(
    `/api/projects/${projectId}/dwg/upload-progress`
  ).then(res => res.data);
export const deleteJsonData = (projectId: string, jsonId: string) =>
  api.delete(`/api/projects/${projectId}/dwg/${jsonId}`);
export const batchDeleteJsonData = (projectId: string, jsonIds: string[]) =>
  api.post<{ success: boolean; deleted: number }>(`/api/projects/${projectId}/dwg/batch-delete`, { json_ids: jsonIds }).then(res => res.data);

// Audit
export const getAuditStatus = (projectId: string) =>
  api.get<AuditStatus>(`/api/projects/${projectId}/audit/status`).then(res => res.data);
export const getThreeLineMatch = (projectId: string) =>
  api.get<ThreeLineMatch>(`/api/projects/${projectId}/audit/three-lines`).then(res => res.data);
export const getAuditResults = (
  projectId: string,
  params?: { version?: number; type?: string; view?: 'grouped' | 'raw' },
) =>
  api.get<AuditResult[]>(`/api/projects/${projectId}/audit/results`, { params }).then(res => res.data);
export const getAuditResultPreview = (projectId: string, resultId: string) =>
  api.get<AuditResultPreview>(`/api/projects/${projectId}/audit/results/${resultId}/preview`).then(res => res.data);
export const batchAuditResultPreview = (projectId: string, resultIds: string[]) =>
  api.post<AuditResultPreview & { extra_source_anchors?: any[]; extra_target_anchors?: any[] }>(
    `/api/projects/${projectId}/audit/results/batch-preview`,
    { result_ids: resultIds },
  ).then(res => res.data);
export const getAuditHistory = (projectId: string) =>
  api.get<any[]>(`/api/projects/${projectId}/audit/history`).then(res => res.data);
export const getAuditEvents = (
  projectId: string,
  params?: { version?: number; since_id?: number; limit?: number; event_kinds?: string },
) =>
  api.get<AuditEventsResponse>(`/api/projects/${projectId}/audit/events`, { params }).then(res => res.data);
export const getAuditEventsStreamUrl = (projectId: string) =>
  `${API_BASE}/api/projects/${projectId}/audit/events/stream`;
export const getAuditResultsStreamUrl = (projectId: string) =>
  `${API_BASE}/api/projects/${projectId}/audit/results/stream`;

export const getFeedbackThreadsStreamUrl = (projectId: string) =>
  `${API_BASE}/api/projects/${projectId}/feedback-threads/stream`;

export const getFeedbackAttachmentUrl = (fileUrl: string) =>
  fileUrl.startsWith('http://') || fileUrl.startsWith('https://') ? fileUrl : `${API_BASE}${fileUrl}`;

export interface AuditResultUpdatePayload {
  is_resolved?: boolean;
  feedback_status?: AuditFeedbackStatus;
  feedback_note?: string;
}

export const updateAuditResult = (
  projectId: string,
  resultId: string,
  payload: AuditResultUpdatePayload,
) =>
  api.patch<AuditResult>(`/api/projects/${projectId}/audit/results/${resultId}`, payload).then(res => res.data);
export const batchUpdateAuditResults = (
  projectId: string,
  resultIds: string[],
  payload: AuditResultUpdatePayload,
) =>
  api.patch<{ success: boolean }>(`/api/projects/${projectId}/audit/results/batch`, {
    result_ids: resultIds,
    ...payload,
  }).then(res => res.data);

export const createFeedbackThread = (
  projectId: string,
  resultId: string,
  payload: { message: string; images?: File[] },
  options?: { auditVersion?: number | null },
) => {
  const params = options?.auditVersion != null ? { audit_version: options.auditVersion } : undefined;
  if (payload.images?.length) {
    const formData = new FormData();
    formData.append('message', payload.message);
    payload.images.forEach((file) => formData.append('images', file));
    return api.post<FeedbackThread>(`/api/projects/${projectId}/audit/results/${resultId}/feedback-thread`, formData, {
      params,
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(res => res.data);
  }
  return api.post<FeedbackThread>(`/api/projects/${projectId}/audit/results/${resultId}/feedback-thread`, { message: payload.message }, {
    params,
  }).then(res => res.data);
};

export const getFeedbackThreadByResult = (
  projectId: string,
  resultId: string,
  options?: { auditVersion?: number | null },
) =>
  api.get<FeedbackThread>(`/api/projects/${projectId}/audit/results/${resultId}/feedback-thread`, {
    params: options?.auditVersion != null ? { audit_version: options.auditVersion } : undefined,
  }).then(res => res.data);

export const listFeedbackThreadsByResults = (
  projectId: string,
  resultIds: string[],
  options?: { auditVersion?: number | null },
) =>
  api.post<FeedbackThread[]>(`/api/projects/${projectId}/feedback-threads/query`, {
    audit_result_ids: resultIds,
    audit_version: options?.auditVersion ?? null,
  }).then(res => res.data);

export const getFeedbackThread = (projectId: string, threadId: string) =>
  api.get<FeedbackThread>(`/api/projects/${projectId}/feedback-threads/${threadId}`).then(res => res.data);

export const getFeedbackThreadMessages = (projectId: string, threadId: string) =>
  api.get<FeedbackThreadMessage[]>(`/api/projects/${projectId}/feedback-threads/${threadId}/messages`).then(res => res.data);

export const appendFeedbackThreadMessage = (
  projectId: string,
  threadId: string,
  payload: { content: string; images?: File[] },
) => {
  if (payload.images?.length) {
    const formData = new FormData();
    formData.append('content', payload.content);
    payload.images.forEach((file) => formData.append('images', file));
    return api.post<FeedbackThread>(`/api/projects/${projectId}/feedback-threads/${threadId}/messages`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(res => res.data);
  }
  return api.post<FeedbackThread>(`/api/projects/${projectId}/feedback-threads/${threadId}/messages`, { content: payload.content }).then(res => res.data);
};
export const startAudit = (
  projectId: string,
  payload?: { allow_incomplete?: boolean; provider_mode?: AuditProviderMode },
) =>
  api.post<{ success: boolean; audit_version: number }>(`/api/projects/${projectId}/audit/start`, payload ?? {}).then(res => res.data);
export const runAudit = (projectId: string) =>
  api.post<{ success: boolean; audit_version: number; total_issues: number }>(`/api/projects/${projectId}/audit/run`)
    .then(res => res.data);
export const stopAudit = (projectId: string) =>
  api.post<{
    success: boolean;
    message: string;
    audit_version?: number;
    stopped?: boolean;
    deleted?: { results: number; runs: number; tasks: number; events: number; feedback_samples: number; issue_drawings: number; annotations: number };
    artifacts?: { cache_files: number; report_files: number };
  }>(`/api/projects/${projectId}/audit/stop`).then(res => res.data);
export const clearAuditReport = (projectId: string) =>
  api.post<{ success: boolean; deleted: { results: number; runs: number; tasks: number } }>(`/api/projects/${projectId}/audit/clear`)
    .then(res => res.data);
export const deleteAuditVersion = (projectId: string, version: number) =>
  api.delete<{ success: boolean; deleted: { results: number; runs: number; tasks: number } }>(
    `/api/projects/${projectId}/audit/version/${version}`,
  ).then(res => res.data);

// Feedback Samples
export type CurationStatus = 'new' | 'accepted' | 'rejected';

export interface FeedbackSample {
  id: string;
  project_id: string;
  audit_result_id: string;
  audit_version: number;
  issue_type: string;
  severity: string | null;
  sheet_no_a: string | null;
  sheet_no_b: string | null;
  location: string | null;
  description: string | null;
  value_a: string | null;
  value_b: string | null;
  user_note: string | null;
  curation_status: CurationStatus;
  created_at: string | null;
  curated_at: string | null;
}

export const getFeedbackSamples = (
  projectId: string,
  params?: { status?: CurationStatus; issue_type?: string },
) =>
  api.get<FeedbackSample[]>(`/api/projects/${projectId}/feedback-samples`, { params }).then(res => res.data);

export const updateSampleCuration = (
  projectId: string,
  sampleId: string,
  curationStatus: CurationStatus,
) =>
  api.patch<{ success: boolean }>(`/api/projects/${projectId}/feedback-samples/${sampleId}`, {
    curation_status: curationStatus,
  }).then(res => res.data);

export const batchUpdateSampleCuration = (
  projectId: string,
  sampleIds: string[],
  curationStatus: CurationStatus,
) =>
  api.patch<{ success: boolean; updated: number }>(`/api/projects/${projectId}/feedback-samples/batch`, {
    sample_ids: sampleIds,
    curation_status: curationStatus,
  }).then(res => res.data);

export const getExportSamplesUrl = (
  projectId: string,
  status: CurationStatus = 'accepted',
) => `${API_BASE}/api/projects/${projectId}/feedback-samples/export?status=${status}`;

export interface FeedbackStats {
  new: number;
  accepted: number;
  rejected: number;
  total: number;
}

export interface FeedbackSampleWithProject extends FeedbackSample {
  project_name: string;
}

export interface ProjectWithSamples {
  id: string;
  name: string;
  sample_count: number;
}

export const getGlobalFeedbackStats = (projectId?: string) =>
  api.get<FeedbackStats>('/api/feedback-samples/stats', {
    params: projectId ? { project_id: projectId } : undefined,
  }).then(res => res.data);

export const getGlobalFeedbackSamples = (
  params?: { project_id?: string; status?: CurationStatus; issue_type?: string },
) =>
  api.get<FeedbackSampleWithProject[]>('/api/feedback-samples/all', { params }).then(res => res.data);

export const getProjectsWithSamples = () =>
  api.get<ProjectWithSamples[]>('/api/feedback-samples/projects').then(res => res.data);

// Report
export const downloadPdfReport = (projectId: string, version?: number) => {
  const url = version
    ? `${API_BASE}/api/projects/${projectId}/report/pdf?version=${version}`
    : `${API_BASE}/api/projects/${projectId}/report/pdf`;
  return url;
};
export const downloadExcelReport = (projectId: string, version?: number) => {
  const url = version
    ? `${API_BASE}/api/projects/${projectId}/report/excel?version=${version}`
    : `${API_BASE}/api/projects/${projectId}/report/excel`;
  return url;
};

export const getDrawingImageUrl = (projectId: string, drawingId: string, cacheVersion?: number) => {
  const suffix = cacheVersion !== undefined ? `?v=${cacheVersion}` : '';
  return `${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/image${suffix}`;
};

export const getJsonThumbnailUrl = (projectId: string, jsonId: string, cacheVersion?: number) => {
  const suffix = cacheVersion !== undefined ? `?v=${cacheVersion}` : '';
  return `${API_BASE}/api/projects/${projectId}/json-data/${jsonId}/thumbnail${suffix}`;
};

export const bindJsonToCatalog = (projectId: string, jsonId: string, catalogId: string) =>
  api.patch<{ success: boolean; json_id: string; catalog_id: string }>(
    `/api/projects/${projectId}/json-data/${jsonId}/bind-catalog`,
    { catalog_id: catalogId }
  ).then(res => res.data);

export default api;
