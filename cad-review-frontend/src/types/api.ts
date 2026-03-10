export type UiPreferencesMap = Record<string, unknown>;
export type AuditProviderMode = 'kimi_sdk' | 'codex_sdk';

export const DEFAULT_AUDIT_PROVIDER_MODE: AuditProviderMode = 'kimi_sdk';
export const AUDIT_PROVIDER_STORAGE_KEY = 'ccad.auditProvider.default';

export interface ProjectUiPreferencesResponse {
  project_id: string;
  preferences: UiPreferencesMap;
}

export interface CatalogUploadItem {
  图号: string;
  图名: string;
}

export interface CatalogUploadResponse {
  success: boolean;
  items: CatalogUploadItem[];
  error?: string;
}

export interface DrawingsUploadResponse {
  success: boolean;
  total: number;
  matched: number;
  unmatched: number;
  version?: number;
}

export interface DwgUploadResultItem {
  dwg: string;
  layout_name: string;
  sheet_no: string;
  sheet_name: string;
  status: string;
  catalog_id: string | null;
  match_score: number;
  json_id: string;
  json_path: string;
  data_version: number;
  is_placeholder?: boolean;
}

export interface DwgUploadSummary {
  dwg_files: number;
  layouts_total: number;
  matched: number;
  unmatched: number;
  skipped_extra_layouts: number;
  placeholder_layouts: number;
}

export interface DwgUploadResponse {
  success: boolean;
  summary: DwgUploadSummary;
  results: DwgUploadResultItem[];
}

export interface AuditHistoryItem {
  version: number;
  status: string;
  current_step?: string | null;
  progress?: number;
  count: number;
  grouped_count?: number;
  types: Record<string, number>;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  scope_mode?: 'full' | 'partial' | null;
}

export interface AuditEvent {
  id: number;
  audit_version: number;
  level: 'info' | 'success' | 'warning' | 'error';
  step_key?: string | null;
  agent_key?: string | null;
  agent_name?: string | null;
  event_kind?: string | null;
  progress_hint?: number | null;
  message: string;
  created_at?: string | null;
  meta: Record<string, unknown>;
}

export interface AuditEventsResponse {
  items: AuditEvent[];
  next_since_id?: number | null;
}

export interface AIPromptStage {
  stage_key: string;
  title: string;
  description: string;
  call_site: string;
  system_prompt: string;
  user_prompt: string;
  default_system_prompt: string;
  default_user_prompt: string;
  is_overridden: boolean;
  placeholders: string[];
  updated_at?: string | null;
}

export interface AIPromptStagesResponse {
  stages: AIPromptStage[];
}

export interface SkillPackStageOption {
  stage_key: string;
  title: string;
  description: string;
}

export interface SkillTypeItem {
  skill_type: string;
  label: string;
  execution_mode: 'code' | 'ai' | 'hybrid';
  default_stage_keys: string[];
  allowed_stages: SkillPackStageOption[];
}

export interface SkillTypesResponse {
  items: SkillTypeItem[];
}

export interface SkillPackItem {
  id: string;
  skill_type: string;
  title: string;
  content: string;
  source: 'manual' | 'auto';
  execution_mode: 'code' | 'ai' | 'hybrid';
  stage_keys: string[];
  source_sample_ids: string[];
  is_active: boolean;
  priority: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface SkillPackListResponse {
  items: SkillPackItem[];
}
