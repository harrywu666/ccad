import { describe, expect, it } from 'vitest';
import { normalizeIssueType, parseLocationText } from '../project-detail/ProjectStepAudit';

describe('ProjectStepAudit compatibility helpers', () => {
  it('normalizes review-kernel issue types to legacy buckets', () => {
    expect(normalizeIssueType('dimension_conflict')).toBe('dimension');
    expect(normalizeIssueType('reference_broken')).toBe('index');
    expect(normalizeIssueType('annotation_missing')).toBe('dimension');
    expect(normalizeIssueType('material')).toBe('material');
  });

  it('parses json location text to readable label', () => {
    expect(parseLocationText('{"sheet_no":"A1.01","logical_sheet_title":"平面布置图"}')).toBe('A1.01 / 平面布置图');
    expect(parseLocationText('{"sheet_no":"A1.01"}')).toBe('A1.01');
    expect(parseLocationText('索引A1')).toBe('索引A1');
  });
});
