import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertCircle, RefreshCw } from 'lucide-react';
import * as api from '@/api';
import AppLayout from '@/components/layout/AppLayout';
import TopHeader from '@/components/layout/TopHeader';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import type { AuditResult, AuditStatus, CatalogItem, Project } from '@/types';
import type { AuditEvent, AuditHistoryItem } from '@/types/api';
import { createAuditEventStreamController } from '@/pages/ProjectDetail/components/auditEventStream';
import { createAuditResultStreamController } from '@/pages/ProjectDetail/components/auditResultStream';

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function readText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function readNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? '');
  }
}

function formatTime(value?: string | null): string {
  if (!value) return '--:--:--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--:--:--';
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}

function formatVersionTime(value?: string | null): string {
  if (!value) return '无时间';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '无时间';
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function isChiefAuditEvent(event: AuditEvent): boolean {
  const meta = asRecord(event.meta);
  const actorRole = readText(meta.actor_role);
  if (actorRole === 'chief') return true;
  if (actorRole === 'worker') return false;
  const agentKey = readText(event.agent_key);
  const agentName = readText(event.agent_name);
  const message = readText(event.message);
  return (
    agentKey.includes('chief')
    || agentKey.includes('kernel')
    || agentName.includes('审图内核')
    || agentName.includes('主审')
    || message.startsWith('审图内核 Agent')
    || message.startsWith('主审 Agent')
  );
}

export function mergeRawIssueRows(current: AuditResult[], incoming: AuditResult[]): AuditResult[] {
  if (incoming.length === 0) return current;
  const next = [...current];
  const indexById = new Map<string, number>();
  next.forEach((item, index) => indexById.set(item.id, index));
  incoming.forEach((item) => {
    const existingIndex = indexById.get(item.id);
    if (existingIndex === undefined) {
      indexById.set(item.id, next.length);
      next.push(item);
      return;
    }
    next[existingIndex] = {
      ...next[existingIndex],
      ...item,
    };
  });
  return next;
}

function mergeEventsById(current: AuditEvent[], incoming: AuditEvent[]): AuditEvent[] {
  if (incoming.length === 0) return current;
  const next = [...current];
  const indexById = new Map<number, number>();
  next.forEach((item, index) => indexById.set(item.id, index));
  incoming.forEach((item) => {
    const existingIndex = indexById.get(item.id);
    if (existingIndex === undefined) {
      indexById.set(item.id, next.length);
      next.push(item);
      return;
    }
    next[existingIndex] = item;
  });
  next.sort((a, b) => a.id - b.id);
  return next;
}

async function loadAllEventsByKind(
  projectId: string,
  version: number,
  eventKind: string,
): Promise<AuditEvent[]> {
  const all: AuditEvent[] = [];
  const seen = new Set<number>();
  let sinceId: number | undefined;
  for (let i = 0; i < 40; i += 1) {
    const response = await api.getAuditEvents(projectId, {
      version,
      since_id: sinceId,
      limit: 200,
      event_kinds: eventKind,
    });
    const items = (Array.isArray(response.items) ? response.items : [])
      .filter((item) => readText(item.event_kind) === eventKind);
    let maxId = sinceId ?? 0;
    let newCount = 0;
    items.forEach((item) => {
      if (!seen.has(item.id)) {
        seen.add(item.id);
        all.push(item);
        newCount += 1;
      }
      if (item.id > maxId) maxId = item.id;
    });
    if (newCount === 0) break;
    const nextSinceId = readNumber(response.next_since_id);
    if (nextSinceId !== null && nextSinceId > maxId) maxId = nextSinceId;
    if (maxId <= (sinceId ?? 0)) break;
    sinceId = maxId;
    if (items.length < 200) break;
  }
  all.sort((a, b) => a.id - b.id);
  return all;
}

function resolveWorkerOutputKey(event: AuditEvent): string[] {
  const meta = asRecord(event.meta);
  const assignmentId = readText(meta.assignment_id);
  const visibleSessionKey = readText(meta.visible_session_key);
  const sessionKey = readText(meta.session_key);
  const keys = [
    assignmentId ? `assignment:${assignmentId}` : '',
    assignmentId,
    visibleSessionKey,
    sessionKey,
  ].filter(Boolean);
  return Array.from(new Set(keys));
}

function sheetLabel(sheetNo?: string | null, catalogMap?: Record<string, string>): string {
  const no = readText(sheetNo);
  if (!no) return '未标注';
  const name = readText(catalogMap?.[no]);
  return name ? `${no} / ${name}` : no;
}

function renderIssueEvidence(value: string | null): string {
  if (!value) return '{}';
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function LogEventCard({ event }: { event: AuditEvent }) {
  return (
    <article className="border border-border bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[13px] font-medium text-foreground break-words">{event.message}</p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {formatTime(event.created_at)} · {readText(event.event_kind) || 'phase_event'}
          </p>
        </div>
        <Badge variant="outline" className="rounded-none">
          {readText(event.level) || 'info'}
        </Badge>
      </div>
      <details className="mt-2">
        <summary className="cursor-pointer text-[12px] text-muted-foreground">查看完整 meta JSON</summary>
        <pre className="mt-2 max-h-56 overflow-auto border border-border bg-secondary/20 p-2 text-[11px]">
          {prettyJson(event.meta)}
        </pre>
      </details>
    </article>
  );
}

export default function AuditLogsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const loadSeqRef = useRef(0);

  const [project, setProject] = useState<Project | null>(null);
  const [auditStatus, setAuditStatus] = useState<AuditStatus | null>(null);
  const [auditHistory, setAuditHistory] = useState<AuditHistoryItem[]>([]);
  const [catalogMap, setCatalogMap] = useState<Record<string, string>>({});
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);

  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [workerCompletedEvents, setWorkerCompletedEvents] = useState<AuditEvent[]>([]);
  const [eventError, setEventError] = useState('');
  const [eventTransport, setEventTransport] = useState<'stream' | 'poll'>('stream');

  const [rawIssueRows, setRawIssueRows] = useState<AuditResult[]>([]);
  const [resultError, setResultError] = useState('');
  const [resultTransport, setResultTransport] = useState<'stream' | 'poll'>('stream');

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!id) return;
    let stopped = false;
    const timer = window.setInterval(async () => {
      try {
        const latest = await api.getAuditStatus(id);
        if (!stopped) setAuditStatus(latest);
      } catch {
        // 保持静默，不打断日志页面浏览
      }
    }, 2500);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [id]);

  useEffect(() => {
    if (!id) return;
    const seq = ++loadSeqRef.current;
    const loadBase = async () => {
      try {
        setLoading(true);
        setError('');
        const [proj, status, history, catalog] = await Promise.all([
          api.getProject(id),
          api.getAuditStatus(id),
          api.getAuditHistory(id).catch(() => []),
          api.getCatalog(id).catch(() => [] as CatalogItem[]),
        ]);
        if (seq !== loadSeqRef.current) return;
        setProject(proj);
        setAuditStatus(status);
        const versions = (Array.isArray(history) ? history : []) as AuditHistoryItem[];
        setAuditHistory(versions);
        const initialVersion = status.audit_version ?? versions[0]?.version ?? null;
        setSelectedVersion(initialVersion);
        const map: Record<string, string> = {};
        (catalog || []).forEach((item) => {
          const sheetNo = readText(item.sheet_no);
          const sheetName = readText(item.sheet_name);
          if (sheetNo && sheetName) {
            map[sheetNo] = sheetName;
          }
        });
        setCatalogMap(map);
      } catch (err: any) {
        if (seq !== loadSeqRef.current) return;
        setError(err?.response?.data?.detail || err?.message || '加载审图日志失败');
      } finally {
        if (seq === loadSeqRef.current) {
          setLoading(false);
        }
      }
    };
    void loadBase();
  }, [id]);

  useEffect(() => {
    if (!id || selectedVersion === null || selectedVersion === undefined) {
      setEvents([]);
      setWorkerCompletedEvents([]);
      setRawIssueRows([]);
      return;
    }
    let stopped = false;
    setEvents([]);
    setWorkerCompletedEvents([]);
    setRawIssueRows([]);
    setEventError('');
    setResultError('');

    const bootstrap = async () => {
      try {
        const [historyEvents, issueRows, allWorkerCompleted] = await Promise.all([
          api.getAuditEvents(id, { version: selectedVersion, limit: 200 }),
          api.getAuditResults(id, { version: selectedVersion, view: 'raw' }),
          loadAllEventsByKind(id, selectedVersion, 'worker_assignment_completed'),
        ]);
        if (stopped) return;
        setEvents(historyEvents.items || []);
        setWorkerCompletedEvents(
          allWorkerCompleted.filter((event) => readText(event.event_kind) === 'worker_assignment_completed'),
        );
        setRawIssueRows((issueRows || []).filter((item) => !item.is_grouped));
      } catch (err: any) {
        if (stopped) return;
        setError(err?.response?.data?.detail || err?.message || '加载版本日志失败');
      }
    };
    void bootstrap();

    const eventController = createAuditEventStreamController({
      projectId: id,
      version: selectedVersion,
      maxEvents: 320,
      onEvents: (items) => {
        setEvents(items);
        setWorkerCompletedEvents((current) => mergeEventsById(
          current,
          items.filter((event) => readText(event.event_kind) === 'worker_assignment_completed'),
        ));
      },
      onError: (message) => setEventError(message),
      onTransportChange: (transport) => setEventTransport(transport),
    });
    const resultController = createAuditResultStreamController({
      projectId: id,
      version: selectedVersion,
      onUpsert: ({ row, rawRows }) => {
        const deltaRows = rawRows.length > 0
          ? rawRows
          : ((!row.is_grouped && row.id) ? [row] : []);
        if (deltaRows.length > 0) {
          setRawIssueRows((current) => mergeRawIssueRows(current, deltaRows));
        }
      },
      onError: (message) => setResultError(message),
      onTransportChange: (transport) => setResultTransport(transport),
    });
    eventController.start();
    resultController.start();

    return () => {
      stopped = true;
      eventController.stop();
      resultController.stop();
    };
  }, [id, selectedVersion]);

  const chiefEvents = useMemo(
    () => events.filter((event) => isChiefAuditEvent(event)),
    [events],
  );
  const runtime = auditStatus?.ui_runtime;
  const chief = runtime?.chief;
  const workerSessions = runtime?.worker_sessions || [];
  const recentCompleted = runtime?.recent_completed || [];
  const finalReviewRuntime = runtime?.final_review;
  const organizerRuntime = runtime?.organizer;
  const workerEvents = useMemo(
    () => workerCompletedEvents,
    [workerCompletedEvents],
  );
  const finalReviewEvents = useMemo(
    () => events.filter((event) => readText(event.event_kind) === 'final_review_decision'),
    [events],
  );
  const workerOutputByKey = useMemo(() => {
    const map = new Map<string, AuditEvent>();
    workerEvents.forEach((event) => {
      resolveWorkerOutputKey(event).forEach((key) => map.set(key, event));
    });
    return map;
  }, [workerEvents]);

  const unresolvedWorkerEvents = useMemo(() => {
    const usedEventIds = new Set<number>();
    const allSessions = [...workerSessions, ...recentCompleted];
    allSessions.forEach((session) => {
      const maybe = workerOutputByKey.get(session.session_key)
        || workerOutputByKey.get(session.session_key.replace(/^assignment:/, ''));
      if (maybe?.id) usedEventIds.add(maybe.id);
    });
    return workerEvents.filter((event) => !usedEventIds.has(event.id));
  }, [workerEvents, workerOutputByKey, workerSessions, recentCompleted]);

  if (loading) {
    return (
      <AppLayout showSidebar={false}>
        <div className="flex h-[50vh] items-center justify-center">
          <RefreshCw className="h-8 w-8 animate-spin text-primary" />
        </div>
      </AppLayout>
    );
  }

  if (!project) {
    return (
      <AppLayout showSidebar={false}>
        <div className="border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive">
          {error || '项目不存在'}
        </div>
      </AppLayout>
    );
  }

  const statusMap: Record<string, { label: string; variant: 'default' | 'secondary' | 'success' | 'warning' | 'destructive' }> = {
    new: { label: '待开始', variant: 'secondary' },
    catalog_locked: { label: '目录已确认', variant: 'warning' },
    matching: { label: '匹配中', variant: 'warning' },
    ready: { label: '待审核', variant: 'warning' },
    auditing: { label: '审核中', variant: 'warning' },
    done: { label: '已完成', variant: 'success' },
    failed: { label: '失败', variant: 'destructive' },
  };

  const renderWorkerSessionCard = (
    session: (typeof workerSessions)[number],
    statusLabel: string,
  ) => {
    const output = workerOutputByKey.get(session.session_key)
      || workerOutputByKey.get(session.session_key.replace(/^assignment:/, ''));
    const outputMeta = asRecord(output?.meta);
    return (
      <article key={`${statusLabel}-${session.session_key}`} className="border border-border bg-secondary/10 p-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-[13px] font-semibold text-foreground">{session.worker_name}</p>
            <p className="text-[12px] text-muted-foreground">{session.skill_label}</p>
          </div>
          <Badge variant="outline" className="rounded-none">{statusLabel}</Badge>
        </div>
        <p className="mt-2 text-[12px] text-foreground">{session.task_title}</p>
        <p className="mt-1 text-[12px] text-muted-foreground">
          {session.context.source_sheet_no || session.context.target_sheet_no
            ? `${sheetLabel(session.context.source_sheet_no, catalogMap)} → ${sheetLabel(session.context.target_sheet_no, catalogMap)}`
            : sheetLabel(session.context.sheet_no, catalogMap)}
        </p>
        <p className="mt-2 text-[12px] text-foreground">{session.current_action}</p>
        {output ? (
          <details className="mt-2">
            <summary className="cursor-pointer text-[12px] text-muted-foreground">查看完整结论 + 证据</summary>
            <div className="mt-2 space-y-2 text-[12px]">
              <p><span className="text-muted-foreground">总结：</span>{readText(outputMeta.summary) || output.message || '—'}</p>
              <p><span className="text-muted-foreground">置信度：</span>{readNumber(outputMeta.confidence) ?? '—'}</p>
              <pre className="max-h-44 overflow-auto border border-border bg-white p-2 text-[11px]">
                {String(outputMeta.markdown_conclusion || outputMeta.worker_markdown_conclusion || '')}
              </pre>
              <pre className="max-h-44 overflow-auto border border-border bg-white p-2 text-[11px]">
                {prettyJson(outputMeta.evidence_bundle || outputMeta.worker_evidence_bundle || {})}
              </pre>
            </div>
          </details>
        ) : (
          <p className="mt-2 text-[12px] text-muted-foreground">这张卡暂未匹配到完整输出事件。</p>
        )}
      </article>
    );
  };

  return (
    <AppLayout showSidebar={false}>
      <TopHeader
        title={`${project.name} · 审图日志`}
        onBack={() => navigate(`/projects/${project.id}`)}
        statusInfo={statusMap[project.status] || { label: '未知', variant: 'default' }}
      />

      <div className="mt-4 flex h-[calc(100vh-220px)] min-h-[620px] flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3 border border-border bg-white p-3">
          <label className="text-[12px] text-muted-foreground" htmlFor="audit-log-version-select">审核版本</label>
          <select
            id="audit-log-version-select"
            data-testid="version-select"
            className="h-9 min-w-[220px] border border-border bg-white px-3 text-[13px]"
            value={selectedVersion ?? ''}
            onChange={(event) => {
              const next = Number(event.target.value);
              setSelectedVersion(Number.isFinite(next) ? next : null);
            }}
          >
            {auditHistory.length === 0 ? (
              <option value="">暂无版本</option>
            ) : auditHistory.map((item) => (
              <option key={item.version} value={item.version}>
                {`v${item.version} · ${formatVersionTime(item.finished_at || item.started_at)} · ${item.grouped_count ?? item.count}条`}
              </option>
            ))}
          </select>
          <Badge variant="outline" className="rounded-none">
            运行状态：{readText(auditStatus?.run_status) || 'unknown'}
          </Badge>
          <Badge variant="outline" className="rounded-none">
            事件通道：{eventTransport}
          </Badge>
          <Badge variant="outline" className="rounded-none">
            问题通道：{resultTransport}
          </Badge>
        </div>

        {(error || eventError || resultError) ? (
          <div className="flex items-center gap-2 border border-destructive/20 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
            <AlertCircle className="h-4 w-4" />
            {error || eventError || resultError}
          </div>
        ) : null}

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-2">
          <section className="flex min-h-[300px] min-w-0 flex-col border border-border bg-white">
            <header className="border-b border-border px-3 py-2">
              <h2 className="text-[14px] font-semibold">审图内核</h2>
              <p className="mt-1 text-[12px] text-muted-foreground">
                {chief?.summary || '审图内核尚未开始本轮调度'}
              </p>
              <p className="text-[12px] text-muted-foreground">
                {chief?.current_action || '等待中'}
              </p>
            </header>
            <div data-testid="chief-scroll" className="min-h-0 flex-1 overflow-auto p-3 space-y-2">
              {chiefEvents.length === 0 ? (
                <p className="text-[12px] text-muted-foreground">暂无审图内核输出。</p>
              ) : chiefEvents.map((event) => (
                <LogEventCard key={event.id} event={event} />
              ))}
            </div>
          </section>

          <section className="flex min-h-[300px] min-w-0 flex-col border border-border bg-white">
            <header className="border-b border-border px-3 py-2">
              <h2 className="text-[14px] font-semibold">副审</h2>
              <p className="mt-1 text-[12px] text-muted-foreground">
                活跃 {workerSessions.length} · 最近完成 {recentCompleted.length}
              </p>
            </header>
            <div data-testid="worker-scroll" className="min-h-0 flex-1 overflow-auto p-3 space-y-3">
              {workerSessions.map((session) => renderWorkerSessionCard(session, session.status))}
              {recentCompleted.map((session) => renderWorkerSessionCard(session, 'completed'))}
              {unresolvedWorkerEvents.length > 0 ? (
                <article className="border border-border bg-white p-3">
                  <p className="text-[12px] font-semibold text-foreground">副审完成原始输出流</p>
                  <div className="mt-2 space-y-2">
                    {unresolvedWorkerEvents.map((event) => {
                      const meta = asRecord(event.meta);
                      return (
                        <details key={`worker-event-${event.id}`} className="border border-border bg-secondary/20 p-2">
                          <summary className="cursor-pointer text-[12px] text-foreground">
                            {event.message || `副审完成事件 #${event.id}`}
                          </summary>
                          <div className="mt-2 space-y-2 text-[12px]">
                            <p className="text-muted-foreground">时间：{formatTime(event.created_at)}</p>
                            <pre className="max-h-40 overflow-auto border border-border bg-white p-2 text-[11px]">
                              {String(meta.markdown_conclusion || meta.worker_markdown_conclusion || '')}
                            </pre>
                            <pre className="max-h-40 overflow-auto border border-border bg-white p-2 text-[11px]">
                              {prettyJson(meta.evidence_bundle || meta.worker_evidence_bundle || {})}
                            </pre>
                          </div>
                        </details>
                      );
                    })}
                  </div>
                </article>
              ) : null}
              {workerSessions.length === 0 && recentCompleted.length === 0 ? (
                <p className="text-[12px] text-muted-foreground">暂无副审日志。</p>
              ) : null}
            </div>
          </section>

          <section className="flex min-h-[300px] min-w-0 flex-col border border-border bg-white">
            <header className="border-b border-border px-3 py-2">
              <h2 className="text-[14px] font-semibold">终审</h2>
              <p className="mt-1 text-[12px] text-muted-foreground">
                {finalReviewRuntime?.summary || '终审尚未开始'}
              </p>
              <p className="text-[12px] text-muted-foreground">
                {finalReviewRuntime?.current_action || '等待审图内核提交候选问题'}
              </p>
              <p className="text-[12px] text-muted-foreground">
                通过 {finalReviewRuntime?.accepted_count ?? 0} · 待补证据 {finalReviewRuntime?.needs_more_evidence_count ?? 0} · 补派 {finalReviewRuntime?.redispatch_count ?? 0}
              </p>
            </header>
            <div data-testid="final-review-scroll" className="min-h-0 flex-1 overflow-auto p-3 space-y-2">
              {finalReviewEvents.length === 0 ? (
                <p className="text-[12px] text-muted-foreground">暂无终审输出。</p>
              ) : finalReviewEvents.map((event) => (
                <LogEventCard key={event.id} event={event} />
              ))}
              {organizerRuntime ? (
                <article className="border border-border bg-secondary/10 p-3">
                  <p className="text-[13px] font-medium text-foreground">结构化整理</p>
                  <p className="mt-1 text-[12px] text-muted-foreground">{organizerRuntime.current_action}</p>
                  <p className="mt-1 text-[12px] text-muted-foreground">{organizerRuntime.summary}</p>
                </article>
              ) : null}
            </div>
          </section>

          <section className="flex min-h-[300px] min-w-0 flex-col border border-border bg-white">
            <header className="border-b border-border px-3 py-2">
              <h2 className="text-[14px] font-semibold">最终问题实时预览（逐条）</h2>
              <p className="mt-1 text-[12px] text-muted-foreground">
                当前 {rawIssueRows.length} 条（不依赖 PNG）
              </p>
            </header>
            <div data-testid="issues-scroll" className="min-h-0 flex-1 overflow-auto p-3 space-y-3">
              {rawIssueRows.length === 0 ? (
                <p className="text-[12px] text-muted-foreground">暂无问题。</p>
              ) : rawIssueRows.map((item) => (
                <article key={item.id} className="border border-border bg-white p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className="rounded-none">{item.severity}</Badge>
                    <Badge variant="outline" className="rounded-none">{item.type}</Badge>
                    <span className="text-[12px] text-muted-foreground">
                      {sheetLabel(item.sheet_no_a, catalogMap)}
                      {item.sheet_no_b ? ` → ${sheetLabel(item.sheet_no_b, catalogMap)}` : ''}
                    </span>
                  </div>
                  <p className="mt-2 text-[12px] text-foreground">{item.location || '未标注定位'}</p>
                  <p className="mt-1 text-[12px] text-foreground">{item.description || '无描述'}</p>
                  <details className="mt-2">
                    <summary className="cursor-pointer text-[12px] text-muted-foreground">查看证据 JSON</summary>
                    <pre className="mt-2 max-h-48 overflow-auto border border-border bg-secondary/20 p-2 text-[11px]">
                      {renderIssueEvidence(item.evidence_json)}
                    </pre>
                  </details>
                </article>
              ))}
            </div>
          </section>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-end">
        <Button
          variant="outline"
          className="rounded-none"
          onClick={async () => {
            if (!id) return;
            const latest = await api.getAuditStatus(id);
            setAuditStatus(latest);
          }}
        >
          刷新状态
        </Button>
      </div>
    </AppLayout>
  );
}
