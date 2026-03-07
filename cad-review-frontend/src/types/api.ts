export type UiPreferencesMap = Record<string, unknown>;

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
