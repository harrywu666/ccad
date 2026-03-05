/**
 * 类型定义
 */

export interface Category {
  id: string;
  name: string;
  color: string;
  sort_order: number;
}

export interface Project {
  id: string;
  name: string;
  category: string | null;
  tags: string | null;
  description: string | null;
  cache_version: number;
  created_at: string;
  status: string;
  updated_at: string;
}

export interface ProjectCreate {
  name: string;
  category?: string;
  tags?: string[];
  description?: string;
}

export interface CatalogItem {
  id: string;
  project_id: string;
  sheet_no: string | null;
  sheet_name: string | null;
  version: string | null;
  date: string | null;
  status: string;
  sort_order: number;
}

export interface Drawing {
  id: string;
  project_id: string;
  catalog_id: string | null;
  sheet_no: string | null;
  sheet_name: string | null;
  png_path: string | null;
  page_index: number | null;
  data_version: number;
  status: string;
}

export interface JsonData {
  id: string;
  project_id: string;
  catalog_id: string | null;
  sheet_no: string | null;
  json_path: string | null;
  data_version: number;
  is_latest: number;
  summary: string | null;
  status: string;
}

export interface AuditResult {
  id: string;
  project_id: string;
  audit_version: number;
  type: string;
  severity: string;
  sheet_no_a: string | null;
  sheet_no_b: string | null;
  location: string | null;
  value_a: string | null;
  value_b: string | null;
  description: string | null;
}

export interface AuditStatus {
  project_id: string;
  status: string;
  audit_version: number | null;
  current_step: string | null;
  progress: number;
  total_issues: number;
  run_status?: string | null;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface ThreeLineAsset {
  id: string;
  sheet_no: string | null;
  sheet_name: string | null;
  data_version: number | null;
  status: string | null;
  png_path?: string | null;
  page_index?: number | null;
  json_path?: string | null;
  summary?: string | null;
  created_at?: string | null;
}

export interface ThreeLineItem {
  catalog_id: string;
  sheet_no: string | null;
  sheet_name: string | null;
  sort_order: number;
  status: 'ready' | 'missing_png' | 'missing_json' | 'missing_all';
  drawing: ThreeLineAsset | null;
  json: ThreeLineAsset | null;
}

export interface ThreeLineSummary {
  total: number;
  ready: number;
  missing_png: number;
  missing_json: number;
  missing_all: number;
}

export interface ThreeLineMatch {
  project_id: string;
  summary: ThreeLineSummary;
  items: ThreeLineItem[];
}

export type MatchFilter = 'all' | 'ready' | 'missing' | 'missing_png' | 'missing_json' | 'missing_all';
