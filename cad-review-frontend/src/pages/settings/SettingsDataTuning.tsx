import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, Download, X } from 'lucide-react';
import * as api from '@/api';
import type { CurationStatus, FeedbackSampleWithProject, FeedbackStats, ProjectWithSamples } from '@/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

const TYPE_LABEL: Record<string, string> = {
  index: '索引',
  dimension: '尺寸',
  material: '材料',
};

const CURATION_LABEL: Record<CurationStatus, string> = {
  new: '待整理',
  accepted: '已采纳',
  rejected: '已排除',
};

const CURATION_BADGE_VARIANT: Record<CurationStatus, 'outline' | 'success' | 'destructive'> = {
  new: 'outline',
  accepted: 'success',
  rejected: 'destructive',
};

type StatusFilter = CurationStatus | 'all';

export default function SettingsDataTuning() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<FeedbackStats>({ new: 0, accepted: 0, rejected: 0, total: 0 });
  const [samples, setSamples] = useState<FeedbackSampleWithProject[]>([]);
  const [projects, setProjects] = useState<ProjectWithSamples[]>([]);
  const [selectedProject, setSelectedProject] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [generatingType, setGeneratingType] = useState<string>('');

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError('');
      const projectParam = selectedProject || undefined;
      const statusParam = statusFilter === 'all' ? undefined : statusFilter;

      const [statsRes, samplesRes, projectsRes] = await Promise.all([
        api.getGlobalFeedbackStats(projectParam),
        api.getGlobalFeedbackSamples({
          project_id: projectParam,
          status: statusParam,
        }),
        api.getProjectsWithSamples(),
      ]);

      setStats(statsRes);
      setSamples(samplesRes);
      setProjects(projectsRes);
    } catch {
      setError('加载样本数据失败，请稍后重试。');
    } finally {
      setLoading(false);
    }
  }, [selectedProject, statusFilter]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const handleCurate = async (sample: FeedbackSampleWithProject, nextStatus: CurationStatus) => {
    const prev = samples;
    setSamples(current =>
      current.map(s => (s.id === sample.id ? { ...s, curation_status: nextStatus } : s)),
    );
    try {
      await api.updateSampleCuration(sample.project_id, sample.id, nextStatus);
      const newStats = await api.getGlobalFeedbackStats(selectedProject || undefined);
      setStats(newStats);
    } catch {
      setSamples(prev);
      setError('操作失败，请重试。');
    }
  };

  const handleExport = () => {
    if (!selectedProject) return;
    window.open(api.getExportSamplesUrl(selectedProject, 'accepted'), '_blank');
  };

  const handleGenerate = async (skillType: string) => {
    try {
      setGeneratingType(skillType);
      setError('');
      const result = await api.generateSkillPacks(skillType);
      const label = TYPE_LABEL[skillType] || skillType;
      setError('');
      if (result.generated > 0) {
        window.alert(`已生成 ${result.generated} 条${label}规则草稿，请到“审查技能包”页查看并启用。`);
        navigate('/settings?tab=skills');
        return;
      }
      window.alert(`当前没有可生成${label}规则的已采纳样本。`);
    } catch {
      setError('生成规则失败，请稍后重试。');
    } finally {
      setGeneratingType('');
    }
  };

  const statCards: { key: StatusFilter; label: string; count: number }[] = [
    { key: 'all', label: '全部样本', count: stats.total },
    { key: 'new', label: '待整理', count: stats.new },
    { key: 'accepted', label: '已采纳', count: stats.accepted },
    { key: 'rejected', label: '已排除', count: stats.rejected },
  ];

  return (
    <>
      <p className="max-w-[780px] text-[15px] leading-7 text-muted-foreground">
        用户在审图报告中标记的误报会自动汇集到这里。你可以逐条审阅，把确认有价值的样本标为"采纳"，然后导出用于 AI 调优。
      </p>

      {error ? (
        <section className="border border-destructive/20 bg-destructive/5 px-5 py-4 text-[14px] text-foreground">
          {error}
        </section>
      ) : null}

      <section className="grid grid-cols-4 gap-4">
        {statCards.map(card => (
          <button
            key={card.key}
            type="button"
            onClick={() => setStatusFilter(card.key)}
            className="text-left"
          >
            <Card className={`rounded-none border shadow-none transition-colors ${
              statusFilter === card.key
                ? 'border-primary bg-primary/5'
                : 'border-border hover:border-primary/40'
            }`}>
              <CardContent className="p-4 space-y-1">
                <div className="text-[13px] text-muted-foreground">{card.label}</div>
                <div className="text-[28px] font-semibold text-foreground tabular-nums">{card.count}</div>
              </CardContent>
            </Card>
          </button>
        ))}
      </section>

      <section className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <label className="text-[13px] text-muted-foreground whitespace-nowrap">项目筛选</label>
          <select
            value={selectedProject}
            onChange={e => setSelectedProject(e.target.value)}
            className="h-9 min-w-[200px] border border-border bg-background px-3 text-[13px] text-foreground outline-none focus:border-primary"
          >
            <option value="">全部项目</option>
            {projects.map(p => (
              <option key={p.id} value={p.id}>
                {p.name}（{p.sample_count}条）
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            className="rounded-none gap-2 text-[13px]"
            disabled={stats.accepted === 0 || generatingType !== ''}
            onClick={() => void handleGenerate('index')}
          >
            {generatingType === 'index' ? '生成中...' : '生成索引规则'}
          </Button>
          <Button
            type="button"
            variant="outline"
            className="rounded-none gap-2 text-[13px]"
            disabled={stats.accepted === 0 || generatingType !== ''}
            onClick={() => void handleGenerate('dimension')}
          >
            {generatingType === 'dimension' ? '生成中...' : '生成尺寸规则'}
          </Button>
          <Button
            type="button"
            variant="outline"
            className="rounded-none gap-2 text-[13px]"
            disabled={stats.accepted === 0 || generatingType !== ''}
            onClick={() => void handleGenerate('material')}
          >
            {generatingType === 'material' ? '生成中...' : '生成材料规则'}
          </Button>
          <Button
            type="button"
            variant="outline"
            className="rounded-none gap-2 text-[13px]"
            disabled={!selectedProject || stats.accepted === 0}
            onClick={handleExport}
          >
            <Download className="h-4 w-4" />
            导出已采纳样本
          </Button>
        </div>
      </section>

      {loading ? (
        <section className="border border-border bg-secondary px-5 py-10 text-[15px] text-muted-foreground text-center">
          正在加载样本数据...
        </section>
      ) : samples.length === 0 ? (
        <section className="border border-border bg-secondary px-5 py-10 text-center">
          <p className="text-[15px] text-muted-foreground">
            {statusFilter !== 'all'
              ? `当前筛选条件下没有${CURATION_LABEL[statusFilter as CurationStatus] || ''}样本。`
              : '还没有用户反馈的误报数据。当用户在审图报告中标记误报后，数据会自动出现在这里。'}
          </p>
        </section>
      ) : (
        <section className="border border-border">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border bg-secondary">
                <th className="px-4 py-3 text-[12px] font-semibold text-foreground w-[72px]">类型</th>
                <th className="px-4 py-3 text-[12px] font-semibold text-foreground">图号</th>
                <th className="px-4 py-3 text-[12px] font-semibold text-foreground">AI 的判断</th>
                <th className="px-4 py-3 text-[12px] font-semibold text-foreground">用户反馈原因</th>
                {!selectedProject ? (
                  <th className="px-4 py-3 text-[12px] font-semibold text-foreground w-[120px]">所属项目</th>
                ) : null}
                <th className="px-4 py-3 text-[12px] font-semibold text-foreground w-[80px] text-center">状态</th>
                <th className="px-4 py-3 text-[12px] font-semibold text-foreground w-[120px] text-center">操作</th>
              </tr>
            </thead>
            <tbody>
              {samples.map(sample => (
                <tr key={sample.id} className="border-b border-border/60 hover:bg-secondary/50 transition-colors">
                  <td className="px-4 py-3">
                    <div className={`inline-flex items-center justify-center border px-2 py-0.5 text-[11px] font-semibold ${
                      sample.curation_status === 'accepted'
                        ? 'border-success/40 bg-success/10 text-success'
                        : 'border-destructive/20 bg-destructive text-white'
                    }`}>
                      {TYPE_LABEL[sample.issue_type] || sample.issue_type}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-[12px] text-foreground">
                    <div className="space-y-0.5">
                      <div><span className="text-muted-foreground">A:</span> {sample.sheet_no_a || '-'}</div>
                      <div><span className="text-muted-foreground">B:</span> {sample.sheet_no_b || '-'}</div>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-[12px] text-muted-foreground max-w-[260px]">
                    <div className="line-clamp-2" title={sample.description || ''}>
                      {sample.description || '-'}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-[12px] text-foreground max-w-[200px]">
                    <div className="line-clamp-2" title={sample.user_note || ''}>
                      {sample.user_note || <span className="text-muted-foreground">未填写</span>}
                    </div>
                  </td>
                  {!selectedProject ? (
                    <td className="px-4 py-3 text-[12px] text-muted-foreground">
                      {sample.project_name}
                    </td>
                  ) : null}
                  <td className="px-4 py-3 text-center">
                    <Badge
                      variant={CURATION_BADGE_VARIANT[sample.curation_status as CurationStatus] || 'outline'}
                      className="rounded-none text-[11px]"
                    >
                      {CURATION_LABEL[sample.curation_status as CurationStatus] || sample.curation_status}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-center gap-1">
                      {sample.curation_status !== 'accepted' ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          className="rounded-none text-success hover:bg-success/10 hover:text-success"
                          title="采纳"
                          onClick={() => void handleCurate(sample, 'accepted')}
                        >
                          <Check className="h-4 w-4" />
                        </Button>
                      ) : null}
                      {sample.curation_status !== 'rejected' ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          className="rounded-none text-destructive hover:bg-destructive/10 hover:text-destructive"
                          title="排除"
                          onClick={() => void handleCurate(sample, 'rejected')}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      ) : null}
                      {sample.curation_status !== 'new' ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          className="rounded-none text-muted-foreground hover:bg-secondary hover:text-foreground"
                          title="重置为待整理"
                          onClick={() => void handleCurate(sample, 'new')}
                        >
                          <span className="text-[11px] font-medium">重置</span>
                        </Button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
