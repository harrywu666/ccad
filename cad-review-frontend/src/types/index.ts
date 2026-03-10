/**
 * 类型定义
 */
import type { AuditProviderMode } from './api';

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

export interface IssueFocusAnchor {
  role?: string | null;
  grid?: string | null;
  global_pct?: {
    x: number;
    y: number;
  } | null;
  origin?: string | null;
  confidence?: number | null;
  anchor_type?: string | null;
  registration_method?: string | null;
  highlight_region?: IssueHighlightRegion | null;
}

export interface IssueHighlightRegion {
  shape?: 'cloud_rect' | null;
  bbox_pct?: {
    x: number;
    y: number;
    width: number;
    height: number;
  } | null;
  origin?: string | null;
}

export interface AuditIssuePreviewDrawingAsset {
  drawing_id: string;
  drawing_data_version: number | null;
  sheet_no: string | null;
  sheet_name: string | null;
  page_index: number | null;
  match_status: string;
  anchor: IssueFocusAnchor | null;
  layout_anchor?: IssueFocusAnchor | null;
  pdf_anchor?: IssueFocusAnchor | null;
  highlight_region?: IssueHighlightRegion | null;
  anchor_status?: 'pdf_ready' | 'pdf_low_confidence' | 'pdf_visual_mismatch' | 'layout_fallback' | 'layout_only' | 'missing' | null;
  registration_confidence?: number | null;
  index_no: string | null;
}

export interface AuditResultPreview {
  issue: {
    id: string;
    audit_version: number;
    type: string | null;
    severity: string | null;
    sheet_no_a: string | null;
    sheet_no_b: string | null;
    location: string | null;
    description: string | null;
  };
  source: AuditIssuePreviewDrawingAsset | null;
  target: AuditIssuePreviewDrawingAsset | null;
  missing_reason: string | null;
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

export type AuditFeedbackStatus = 'none' | 'incorrect';

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
  rule_id: string | null;
  finding_type: string | null;
  finding_status: 'confirmed' | 'suspected' | 'needs_review' | null;
  source_agent: string | null;
  evidence_pack_id: string | null;
  review_round: number;
  triggered_by: string | null;
  confidence: number | null;
  description: string | null;
  evidence_json: string | null;
  locations: string[];
  occurrence_count: number;
  is_resolved: boolean;
  resolved_at: string | null;
  feedback_status: AuditFeedbackStatus;
  feedback_at: string | null;
  feedback_note: string | null;
  is_grouped: boolean;
  group_id: string | null;
  issue_ids: string[];
}

export interface AuditStatus {
  project_id: string;
  status: string;
  audit_version: number | null;
  current_step: string | null;
  progress: number;
  total_issues: number;
  run_status?: string | null;
  provider_mode?: AuditProviderMode | null;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  scope_mode?: 'full' | 'partial' | null;
  scope_summary?: string | null;
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
  is_placeholder?: boolean | null;
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

export interface UnmatchedJson {
  id: string;
  sheet_no: string | null;
  layout_name: string | null;
  source_dwg: string | null;
  thumbnail_path: string | null;
  json_path: string | null;
  data_version: number | null;
  status: string | null;
  created_at: string | null;
}

export interface ThreeLineMatch {
  project_id: string;
  summary: ThreeLineSummary;
  items: ThreeLineItem[];
  unmatched_jsons?: UnmatchedJson[];
}

export type MatchFilter = 'all' | 'ready' | 'missing' | 'missing_png' | 'missing_json' | 'missing_all';
