import { useEffect, useState, type ReactNode } from 'react';
import axios from 'axios';
import * as api from '@/api';
import {
  AUDIT_PROVIDER_STORAGE_KEY,
  type AgentAssetItem,
} from '@/types/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import SettingsFeedbackAgentPrompts from './SettingsFeedbackAgentPrompts';
import SettingsLegacyStagePrompts from './SettingsLegacyStagePrompts';
import SettingsReviewWorkerSkills from './SettingsReviewWorkerSkills';
import SettingsFileEditorDialog from './SettingsFileEditorDialog';

type AgentId = 'chief_review' | 'review_worker' | 'runtime_guardian';

type EditableAgentAsset = AgentAssetItem & {
  draftContent: string;
  dirty: boolean;
  justSaved: boolean;
};

type AgentCardCopy = {
  title: string;
  summary: string;
  details: string;
};

const AGENT_CARD_COPY: Record<AgentId, AgentCardCopy> = {
  chief_review: {
    title: '主审 Agent',
    summary: '负责先看全局、生成怀疑卡、分发副审任务，并在最后收敛结果。',
    details: '这里直接对应主审运行时真正读取的 AGENTS.md / SOUL.md / MEMORY.md。',
  },
  review_worker: {
    title: '副审 Worker Agent',
    summary: '负责真正落地各类专项核查。下面的 Worker Skills 会进一步定义不同核查能力怎么工作。',
    details: '这里是 review_worker 自己的总规则，不是具体 skill 的说明文件。',
  },
  runtime_guardian: {
    title: '运行守护 Agent',
    summary: '负责看守运行状态、识别卡死和异常输出，并决定何时介入恢复。',
    details: '这里直接对应运行守护 Agent 在运行时读取的 md 文件。',
  },
};

const AGENT_ORDER: AgentId[] = ['chief_review', 'review_worker', 'runtime_guardian'];

type AgentGroupState = {
  loading: boolean;
  saving: boolean;
  savingKey: string | null;
  error: string;
  saveMessage: string;
  items: EditableAgentAsset[];
};

function toEditableAsset(item: AgentAssetItem): EditableAgentAsset {
  return {
    ...item,
    draftContent: item.content,
    dirty: false,
    justSaved: false,
  };
}

function createInitialGroupState(): AgentGroupState {
  return {
    loading: true,
    saving: false,
    savingKey: null,
    error: '',
    saveMessage: '',
    items: [],
  };
}

function AgentAssetCard({
  title,
  summary,
  details,
  items,
  loading,
  saving,
  savingKey,
  error,
  saveMessage,
  onChange,
  onSave,
  onSaveAll,
  children,
}: {
  title: string;
  summary: string;
  details: string;
  items: EditableAgentAsset[];
  loading: boolean;
  saving: boolean;
  savingKey: string | null;
  error: string;
  saveMessage: string;
  onChange: (key: EditableAgentAsset['key'], value: string) => void;
  onSave: (key?: EditableAgentAsset['key']) => Promise<void>;
  onSaveAll: () => Promise<void>;
  children?: ReactNode;
}) {
  const hasUnsavedChanges = items.some(item => item.dirty);
  const [activeKey, setActiveKey] = useState<EditableAgentAsset['key'] | null>(null);
  const activeItem = activeKey ? items.find(item => item.key === activeKey) ?? null : null;

  return (
    <>
      <Card className="rounded-none border border-border shadow-none">
        <CardHeader className="gap-3 border-b border-border/80 pb-5">
          <div className="flex items-start justify-between gap-6">
            <div className="space-y-3">
              <CardTitle className="text-[24px] font-semibold text-foreground">{title}</CardTitle>
              <CardDescription className="max-w-[980px] text-[14px] leading-7 text-muted-foreground">
                {summary}
              </CardDescription>
              <div className="border-l-2 border-primary pl-3 text-[13px] leading-6 text-foreground">
                {details}
              </div>
            </div>
            <Button
              type="button"
              className="h-11 shrink-0 rounded-none px-6 text-[14px]"
              onClick={() => void onSaveAll()}
              disabled={saving || !hasUnsavedChanges}
            >
              {saving ? '保存中...' : '保存全部'}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-6 pt-6">
          {saveMessage ? (
            <section className="border border-success/30 bg-success/10 px-5 py-4 text-[14px] text-foreground">
              {saveMessage}
            </section>
          ) : null}

          {error ? (
            <section className="border border-destructive/20 bg-destructive/5 px-5 py-4 text-[14px] text-foreground">
              {error}
            </section>
          ) : null}

          {loading ? (
            <section className="border border-border bg-secondary px-5 py-10 text-[15px] text-muted-foreground">
              正在读取 Agent 文件...
            </section>
          ) : (
            <div className="grid gap-4 md:grid-cols-3">
              {items.map(item => (
                <section
                  key={item.key}
                  className="h-full rounded-none border border-border/80 bg-secondary/20 px-5 py-5"
                >
                  <div className="flex h-full flex-col gap-4">
                    <div className="flex-1 space-y-3">
                      <div className="flex flex-wrap items-center gap-3">
                        <div className="text-[18px] font-semibold text-foreground">{item.title}</div>
                        <Badge variant="outline" className="rounded-none">
                          {item.file_name}
                        </Badge>
                        {item.dirty ? (
                          <Badge variant="secondary" className="rounded-none border border-amber-300 bg-amber-50 text-amber-900">
                            未保存
                          </Badge>
                        ) : item.justSaved ? (
                          <Badge variant="secondary" className="rounded-none border border-emerald-300 bg-emerald-50 text-emerald-900">
                            已保存
                          </Badge>
                        ) : null}
                      </div>
                      <div className="text-[14px] leading-7 text-muted-foreground">
                        {item.description}
                      </div>
                    </div>
                    <Button
                      type="button"
                      className="mt-auto rounded-none self-start"
                      onClick={() => setActiveKey(item.key)}
                    >
                      编辑 {item.file_name}
                    </Button>
                  </div>
                </section>
              ))}
            </div>
          )}

          {children}
        </CardContent>
      </Card>

      {activeItem ? (
        <SettingsFileEditorDialog
          open={Boolean(activeItem)}
          onOpenChange={open => {
            if (!open) setActiveKey(null);
          }}
          title={activeItem.title}
          description={activeItem.description}
          fileLabel={activeItem.file_name}
          statusLabel={activeItem.dirty ? '未保存' : activeItem.justSaved ? '已保存' : undefined}
          statusTone={activeItem.justSaved ? 'success' : 'warning'}
          value={activeItem.draftContent}
          onChange={value => onChange(activeItem.key, value)}
          onSave={async () => {
            await onSave(activeItem.key);
          }}
          saveDisabled={!activeItem.dirty}
          saving={savingKey === activeItem.key}
        />
      ) : null}
    </>
  );
}

function getErrorMessage(value: unknown, fallback: string) {
  if (axios.isAxiosError(value)) {
    if (typeof value.response?.data?.detail === 'string') return value.response.data.detail;
    return value.message || fallback;
  }
  if (value instanceof Error && value.message) return value.message;
  return fallback;
}

export default function SettingsPrompts() {
  const [groups, setGroups] = useState<Record<AgentId, AgentGroupState>>({
    chief_review: createInitialGroupState(),
    review_worker: createInitialGroupState(),
    runtime_guardian: createInitialGroupState(),
  });

  const updateGroup = (agentId: AgentId, patch: Partial<AgentGroupState>) => {
    setGroups(current => ({
      ...current,
      [agentId]: {
        ...current[agentId],
        ...patch,
      },
    }));
  };

  const loadGroup = async (agentId: AgentId) => {
    try {
      updateGroup(agentId, { loading: true, error: '' });
      const response = await api.getAgentAssets(agentId);
      updateGroup(agentId, {
        items: response.items.map(toEditableAsset),
        loading: false,
      });
    } catch (value) {
      updateGroup(agentId, {
        loading: false,
        error: getErrorMessage(value, '读取 Agent 文件失败。'),
      });
    }
  };

  useEffect(() => {
    AGENT_ORDER.forEach(agentId => {
      void loadGroup(agentId);
    });
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.removeItem(AUDIT_PROVIDER_STORAGE_KEY);
  }, []);

  const handleAssetChange = (
    agentId: AgentId,
    key: EditableAgentAsset['key'],
    value: string,
  ) => {
    setGroups(current => ({
      ...current,
      [agentId]: {
        ...current[agentId],
        saveMessage: '',
        items: current[agentId].items.map(item =>
          item.key === key
            ? {
                ...item,
                draftContent: value,
                dirty: value !== item.content,
                justSaved: false,
              }
            : item,
        ),
      },
    }));
  };

  const handleSaveAgentAssets = async (agentId: AgentId, key?: EditableAgentAsset['key']) => {
    const group = groups[agentId];
    const targetItems = group.items.filter(item => item.dirty && (!key || item.key === key));
    if (targetItems.length === 0) return;

    try {
      updateGroup(agentId, {
        error: '',
        saveMessage: '',
        saving: !key,
        savingKey: key || null,
      });
      const response = await api.updateAgentAssets(
        agentId,
        targetItems.map(item => ({
          key: item.key,
          content: item.draftContent,
        })),
      );
      updateGroup(agentId, {
        items: response.items.map(item => ({
          ...toEditableAsset(item),
          justSaved: !key || item.key === key,
        })),
        saveMessage: key
          ? `"${group.items.find(item => item.key === key)?.title || key}" 已保存，后面新的 Agent 运行会直接用这版内容。`
          : `${AGENT_CARD_COPY[agentId].title} 已保存，后面新的 Agent 运行会直接用这版内容。`,
      });
    } catch (value) {
      updateGroup(agentId, {
        error: getErrorMessage(value, '保存 Agent 文件失败。'),
      });
    } finally {
      updateGroup(agentId, {
        saving: false,
        savingKey: null,
      });
    }
  };

  return (
    <>
      <section className="flex items-start justify-between gap-6">
        <p className="max-w-[780px] text-[15px] leading-7 text-muted-foreground">
          这里不再按零散 prompt 来管，而是直接按 Agent 和 Worker Skill 来管 md 文件。你改完保存，后面新发起的主审、副审、运行守护和误报反馈流程都会直接吃这版内容。
        </p>
      </section>

      <Card className="rounded-none border border-border shadow-none">
        <CardHeader>
          <CardTitle>默认审核引擎</CardTitle>
          <CardDescription>
            Codex 路线已经下线，后面新发起的审核固定走 OpenRouter。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="border border-border bg-secondary px-4 py-4 text-[14px] leading-7 text-foreground">
            当前固定引擎：<span className="font-semibold">OpenRouter</span>。旧的本地默认值缓存会在这里自动清掉。
          </div>
        </CardContent>
      </Card>

      <section className="border border-primary/20 bg-primary/5 px-5 py-4 text-[14px] leading-7 text-foreground">
        这里展示的是会真正调用 AI 的 Agent 和 review_worker 下已经 skill 化的能力文件。
        旧的 stage prompt 还没彻底下线，所以我把它们收到下面的兼容层里，不再占主视角。
      </section>

      {AGENT_ORDER.map(agentId => (
        <AgentAssetCard
          key={agentId}
          title={AGENT_CARD_COPY[agentId].title}
          summary={AGENT_CARD_COPY[agentId].summary}
          details={AGENT_CARD_COPY[agentId].details}
          items={groups[agentId].items}
          loading={groups[agentId].loading}
          saving={groups[agentId].saving}
          savingKey={groups[agentId].savingKey}
          error={groups[agentId].error}
          saveMessage={groups[agentId].saveMessage}
          onChange={(key, value) => handleAssetChange(agentId, key, value)}
          onSave={key => handleSaveAgentAssets(agentId, key)}
          onSaveAll={() => handleSaveAgentAssets(agentId)}
        >
          {agentId === 'review_worker' ? <SettingsReviewWorkerSkills /> : null}
        </AgentAssetCard>
      ))}

      <SettingsFeedbackAgentPrompts />

      <details className="rounded-none border border-border shadow-none" data-testid="legacy-stage-settings">
        <summary className="cursor-pointer list-none border-b border-border/80 px-6 py-5 text-[20px] font-semibold text-foreground">
          旧版阶段设置（兼容层）
        </summary>
        <div className="px-6 py-6">
          <div className="mb-6 border-l-2 border-primary pl-3 text-[13px] leading-6 text-foreground">
            这里放的不是 Agent md 文件，而是还没有完全收编进新架构的旧版运行时模板。默认收起，避免主界面继续被“提示词设置”带偏。
          </div>
          <SettingsLegacyStagePrompts />
        </div>
      </details>
    </>
  );
}
