import axios from 'axios';
import type { Category, Project, ProjectCreate, CatalogItem, Drawing, JsonData, AuditResult, AuditStatus } from '@/types';

const API_BASE = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:7000').replace(/\/$/, '');

const api = axios.create({
  baseURL: API_BASE,
  timeout: 300000,
});

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

// Catalog
export const getCatalog = (projectId: string) =>
  api.get<CatalogItem[]>(`/api/projects/${projectId}/catalog`).then(res => res.data);
export const uploadCatalog = (projectId: string, file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post<{ success: boolean; items: any[] }>(
    `/api/projects/${projectId}/catalog/upload`, formData, { headers: { 'Content-Type': 'multipart/form-data' } }
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
export const uploadDrawings = (projectId: string, file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post<{ success: boolean; total: number; matched: number; unmatched: number }>(
    `/api/projects/${projectId}/drawings/upload`, formData, { headers: { 'Content-Type': 'multipart/form-data' } }
  ).then(res => res.data);
};
export const updateDrawing = (projectId: string, drawingId: string, catalogId: string) =>
  api.put<{ success: boolean }>(`/api/projects/${projectId}/drawings/${drawingId}`, { catalog_id: catalogId })
    .then(res => res.data);
export const deleteDrawings = (projectId: string) =>
  api.delete(`/api/projects/${projectId}/drawings`);

// DWG
export const getJsonDataList = (projectId: string) =>
  api.get<JsonData[]>(`/api/projects/${projectId}/dwg`).then(res => res.data);
export const uploadDwg = (projectId: string, files: File[]) => {
  const formData = new FormData();
  files.forEach(f => formData.append('files', f));
  return api.post<{ success: boolean; results: any[] }>(
    `/api/projects/${projectId}/dwg/upload`, formData, { headers: { 'Content-Type': 'multipart/form-data' } }
  ).then(res => res.data);
};
export const deleteJsonData = (projectId: string, jsonId: string) =>
  api.delete(`/api/projects/${projectId}/dwg/${jsonId}`);

// Audit
export const getAuditStatus = (projectId: string) =>
  api.get<AuditStatus>(`/api/projects/${projectId}/audit/status`).then(res => res.data);
export const getAuditResults = (projectId: string, params?: { version?: number; type?: string }) =>
  api.get<AuditResult[]>(`/api/projects/${projectId}/audit/results`, { params }).then(res => res.data);
export const getAuditHistory = (projectId: string) =>
  api.get<any[]>(`/api/projects/${projectId}/audit/history`).then(res => res.data);
export const startAudit = (projectId: string) =>
  api.post<{ success: boolean; audit_version: number }>(`/api/projects/${projectId}/audit/start`).then(res => res.data);
export const runAudit = (projectId: string) =>
  api.post<{ success: boolean; audit_version: number; total_issues: number }>(`/api/projects/${projectId}/audit/run`)
    .then(res => res.data);

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

export default api;
