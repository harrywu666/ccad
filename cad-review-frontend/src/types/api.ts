export type UiPreferencesMap = Record<string, unknown>;
export type AuditProviderMode = 'api' | 'kimi_sdk' | 'sdk' | 'cli' | 'auto';

export const DEFAULT_AUDIT_PROVIDER_MODE: AuditProviderMode = 'api';
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

export interface AgentAssetGroupSummary {
  agent_id: string;
  title: string;
}

export interface AgentAssetGroupListResponse {
  items: AgentAssetGroupSummary[];
}

export interface AgentAssetItem {
  key: string;
  title: string;
  description: string;
  file_name: string;
  content: string;
}

export interface AgentAssetsResponse {
  agent_id: string;
  title: string;
  items: AgentAssetItem[];
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

export interface AuditRuntimeSummaryAgentItem {
  agent_key: string;
  agent_name: string;
  report_count: number;
  help_requested_count: number;
  help_resolved_count: number;
  output_unstable_count: number;
}

export interface AuditRuntimeSummaryNoteItem {
  event_kind: string;
  message: string;
  agent_name?: string | null;
  created_at?: string | null;
}

export interface AuditRuntimeSummaryItem {
  project_id: string;
  project_name: string;
  audit_version: number;
  status: string;
  current_step?: string | null;
  provider_mode?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  duration_seconds?: number | null;
  counts: {
    agent_status_reported: number;
    runner_help_requested: number;
    runner_help_resolved: number;
    output_validation_failed: number;
    runner_observer_action: number;
  };
  agent_summaries: AuditRuntimeSummaryAgentItem[];
  recent_notes: AuditRuntimeSummaryNoteItem[];
}

export interface AuditRuntimeSummaryResponse {
  items: AuditRuntimeSummaryItem[];
}

export interface FeedbackAgentPromptAsset {
  key: 'prompt' | 'agent' | 'soul';
  title: string;
  description: string;
  file_name: string;
  content: string;
}

export interface FeedbackAgentPromptAssetsResponse {
  items: FeedbackAgentPromptAsset[];
}

export interface FeedbackThreadMessage {
  attachments?: FeedbackThreadMessageAttachment[];
  id: string;
  thread_id: string;
  role: 'user' | 'agent' | 'system';
  message_type: 'claim' | 'question' | 'answer' | 'decision' | 'note';
  content: string;
  structured_json?: string | null;
  created_at?: string | null;
}

export interface FeedbackThreadMessageAttachment {
  id: string;
  file_name: string;
  mime_type: string;
  file_size: number;
  file_url: string;
  created_at?: string | null;
}

export interface FeedbackThread {
  id: string;
  project_id: string;
  audit_result_id: string;
  result_group_id?: string | null;
  audit_version: number;
  status: 'open' | 'agent_reviewing' | 'agent_needs_user_input' | 'resolved_incorrect' | 'resolved_not_incorrect' | 'agent_unavailable' | 'escalated_to_human' | 'closed';
  learning_decision: 'pending' | 'accepted_for_learning' | 'rejected_for_learning' | 'needs_human_review' | 'record_only';
  agent_decision?: string | null;
  agent_confidence?: number | null;
  opened_by?: string | null;
  source_agent?: string | null;
  rule_id?: string | null;
  issue_type?: string | null;
  summary?: string | null;
  resolution_reason?: string | null;
  escalation_reason?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  closed_at?: string | null;
  messages: FeedbackThreadMessage[];
}
