import { describe, expect, it } from 'vitest';
import type { AuditResult } from '@/types';
import { upsertAuditResultRow } from '../../../ProjectDetail';

const buildResult = (overrides: Partial<AuditResult> = {}): AuditResult => ({
  id: 'group_1',
  project_id: 'proj-1',
  audit_version: 1,
  type: 'index',
  severity: 'warning',
  sheet_no_a: 'G0.03',
  sheet_no_b: 'G0.04b',
  location: '索引A1',
  value_a: null,
  value_b: null,
  rule_id: null,
  finding_type: null,
  finding_status: 'confirmed',
  source_agent: 'index_review_agent',
  evidence_pack_id: null,
  review_round: 1,
  triggered_by: null,
  confidence: 0.9,
  description: '索引缺失',
  evidence_json: '{"anchors":[]}',
  locations: ['索引A1'],
  occurrence_count: 1,
  is_resolved: false,
  resolved_at: null,
  feedback_status: 'none',
  feedback_at: null,
  feedback_note: null,
  is_grouped: true,
  group_id: 'group_1',
  issue_ids: ['issue_1'],
  ...overrides,
});

describe('ProjectDetail incremental result merge', () => {
  it('appends a new row to the tail when row id does not exist', () => {
    const row1 = buildResult({ id: 'group_1' });
    const row2 = buildResult({ id: 'group_2', type: 'dimension' });
    const merged = upsertAuditResultRow([row1], row2);

    expect(merged).toHaveLength(2);
    expect(merged[0]).toBe(row1);
    expect(merged[1].id).toBe('group_2');
  });

  it('updates existing row in place order without reordering others', () => {
    const row1 = buildResult({ id: 'group_1', description: '旧描述' });
    const row2 = buildResult({ id: 'group_2', description: '第二条' });
    const updated = buildResult({ id: 'group_1', description: '新描述', evidence_json: '{"anchors":[1]}' });

    const merged = upsertAuditResultRow([row1, row2], updated);

    expect(merged).toHaveLength(2);
    expect(merged[0].id).toBe('group_1');
    expect(merged[0].description).toBe('新描述');
    expect(merged[1]).toBe(row2);
  });
});

