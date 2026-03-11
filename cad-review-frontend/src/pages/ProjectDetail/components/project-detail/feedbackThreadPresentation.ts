import type { FeedbackThread } from '@/types/api';

const THREAD_STATUS_LABEL: Record<string, string> = {
  open: '刚开始处理',
  agent_reviewing: 'Agent 正在判断',
  agent_needs_user_input: '还需要你补一句',
  resolved_incorrect: '已判定为误报',
  resolved_not_incorrect: '暂不认定为误报',
  agent_unavailable: 'Agent 未联通',
  escalated_to_human: '已转人工复核',
  closed: '会话已结束',
};

const LEARNING_DECISION_LABEL: Record<string, string> = {
  pending: '还没决定是否学习',
  accepted_for_learning: '已纳入学习',
  rejected_for_learning: '这条不进入学习',
  needs_human_review: '学习前还要人工复核',
  record_only: '仅记录，不学习',
};

export function getThreadStatusLabel(status?: FeedbackThread['status'] | null) {
  return THREAD_STATUS_LABEL[status || ''] || '等待处理';
}

export function getLearningDecisionLabel(decision?: FeedbackThread['learning_decision'] | null) {
  return LEARNING_DECISION_LABEL[decision || ''] || '还没决定是否学习';
}
