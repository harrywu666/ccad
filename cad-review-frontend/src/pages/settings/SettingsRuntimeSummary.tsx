import { useEffect, useState } from 'react';
import * as api from '@/api';
import type { AuditRuntimeSummaryItem } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

function formatDuration(seconds?: number | null) {
  if (!seconds || seconds <= 0) return '用时未记录';
  const minutes = Math.floor(seconds / 60);
  const remain = seconds % 60;
  if (minutes <= 0) return `${remain} 秒`;
  return `${minutes} 分 ${remain} 秒`;
}

function formatTime(value?: string | null) {
  if (!value) return '未记录';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

export default function SettingsRuntimeSummary() {
  const [items, setItems] = useState<AuditRuntimeSummaryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        setError('');
        const response = await api.getAuditRuntimeSummaries();
        setItems(response.items);
      } catch {
        setError('读取内部运行总结失败，请稍后重试。');
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, []);

  return (
    <>
      <p className="max-w-[900px] text-[15px] leading-7 text-muted-foreground">
        这里放的是开发层内部运行总结，不会进普通用户的审图报告。每轮审图结束后，再统一把哪个 Agent 不稳、Runner 帮了几次、最近卡在什么地方汇总到这里。
      </p>

      {error ? (
        <section className="border border-destructive/20 bg-destructive/5 px-5 py-4 text-[14px] text-foreground">
          {error}
        </section>
      ) : null}

      {loading ? (
        <section className="border border-border bg-secondary px-5 py-10 text-[15px] text-muted-foreground">
          正在整理最近几轮内部运行总结...
        </section>
      ) : items.length === 0 ? (
        <section className="border border-border bg-secondary px-5 py-10 text-center text-[15px] text-muted-foreground">
          最近还没有已结束审图的内部运行总结。
        </section>
      ) : (
        <section className="flex flex-col gap-5">
          {items.map(item => (
            <Card key={`${item.project_id}-${item.audit_version}`} className="rounded-none border border-border shadow-none">
              <CardHeader className="border-b border-border/70 pb-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="space-y-2">
                    <CardTitle className="text-[22px] font-semibold text-foreground">
                      {item.project_name} · v{item.audit_version}
                    </CardTitle>
                    <div className="flex flex-wrap gap-3 text-[13px] text-muted-foreground">
                      <span>结束时间：{formatTime(item.finished_at)}</span>
                      <span>总用时：{formatDuration(item.duration_seconds)}</span>
                      <span>引擎：{item.provider_mode || '未记录'}</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-right text-[13px]">
                    <div>
                      <div className="text-muted-foreground">内部日报</div>
                      <div className="text-[20px] font-semibold text-foreground">{item.counts.agent_status_reported}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground">求助次数</div>
                      <div className="text-[20px] font-semibold text-foreground">{item.counts.runner_help_requested}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground">已处理</div>
                      <div className="text-[20px] font-semibold text-foreground">{item.counts.runner_help_resolved}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground">输出不稳</div>
                      <div className="text-[20px] font-semibold text-foreground">{item.counts.output_validation_failed}</div>
                    </div>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="grid gap-5 p-5 lg:grid-cols-[1.1fr_0.9fr]">
                <section className="space-y-3">
                  <h3 className="text-[15px] font-semibold text-foreground">各 Agent 运行情况</h3>
                  <div className="space-y-3">
                    {item.agent_summaries.length === 0 ? (
                      <div className="border border-border bg-secondary px-4 py-4 text-[14px] text-muted-foreground">
                        这轮没有记录到明显的内部求助。
                      </div>
                    ) : (
                      item.agent_summaries.map(agent => (
                        <div key={agent.agent_key} className="border border-border bg-secondary/50 px-4 py-4">
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-[15px] font-medium text-foreground">{agent.agent_name}</div>
                            <div className="text-[12px] text-muted-foreground">{agent.agent_key}</div>
                          </div>
                          <div className="mt-3 grid grid-cols-4 gap-3 text-[13px]">
                            <div>
                              <div className="text-muted-foreground">日报</div>
                              <div className="font-semibold text-foreground">{agent.report_count}</div>
                            </div>
                            <div>
                              <div className="text-muted-foreground">求助</div>
                              <div className="font-semibold text-foreground">{agent.help_requested_count}</div>
                            </div>
                            <div>
                              <div className="text-muted-foreground">已解</div>
                              <div className="font-semibold text-foreground">{agent.help_resolved_count}</div>
                            </div>
                            <div>
                              <div className="text-muted-foreground">不稳</div>
                              <div className="font-semibold text-foreground">{agent.output_unstable_count}</div>
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </section>

                <section className="space-y-3">
                  <h3 className="text-[15px] font-semibold text-foreground">最近内部备注</h3>
                  <div className="space-y-3">
                    {item.recent_notes.length === 0 ? (
                      <div className="border border-border bg-secondary px-4 py-4 text-[14px] text-muted-foreground">
                        这轮没有额外的内部备注。
                      </div>
                    ) : (
                      item.recent_notes.map((note, index) => (
                        <div key={`${note.event_kind}-${index}`} className="border border-border bg-secondary/50 px-4 py-4">
                          <div className="flex items-center justify-between gap-3 text-[12px] text-muted-foreground">
                            <span>{note.agent_name || note.event_kind}</span>
                            <span>{formatTime(note.created_at)}</span>
                          </div>
                          <p className="mt-2 text-[14px] leading-6 text-foreground">{note.message}</p>
                        </div>
                      ))
                    )}
                  </div>
                </section>
              </CardContent>
            </Card>
          ))}
        </section>
      )}
    </>
  );
}
