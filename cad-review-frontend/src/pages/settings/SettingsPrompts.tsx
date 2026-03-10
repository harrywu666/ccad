import { useEffect, useState } from 'react';
import { useBeforeUnload } from 'react-router-dom';
import axios from 'axios';
import * as api from '@/api';
import {
  AUDIT_PROVIDER_STORAGE_KEY,
  DEFAULT_AUDIT_PROVIDER_MODE,
  type AIPromptStage,
  type AuditProviderMode,
} from '@/types/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { AuditProviderSelector, getAuditProviderLabel } from '../ProjectDetail/components/AuditProgressDialog';

type EditablePromptStage = AIPromptStage & {
  draftSystemPrompt: string;
  draftUserPrompt: string;
  dirty: boolean;
  pendingReset: boolean;
  justSaved: boolean;
};

const textareaClassName =
  'min-h-[220px] w-full resize-y border border-border bg-secondary px-4 py-4 text-[14px] leading-7 text-foreground outline-none transition-colors focus:border-primary';

const statusTone: Record<string, 'outline' | 'warning' | 'success'> = {
  default: 'outline',
  dirty: 'warning',
  saved: 'success',
};

type PromptAgentGroup = {
  key: string;
  title: string;
  summary: string;
  details: string;
  stageKeys: string[];
};

const PROMPT_AGENT_GROUPS: PromptAgentGroup[] = [
  {
    key: 'drawing-recognition-agent',
    title: '图纸识别Agent',
    summary: '负责目录识别、图纸识别、识别结果汇总和目录匹配校验。',
    details: '主要功能：把目录和图纸页识别成可用的图号、图名和匹配关系，给后续审图流程提供基础输入。',
    stageKeys: [
      'catalog_recognition',
      'sheet_recognition',
      'sheet_summarization',
      'sheet_catalog_validation',
    ],
  },
  {
    key: 'master-planner-agent',
    title: '总控规划Agent',
    summary: '负责先看全局上下文，决定后面要查哪些图、哪些图之间要互相对照。',
    details: '主要功能：基于图纸上下文和关系边生成任务图，控制正式审图前的优先级和任务范围。',
    stageKeys: ['master_task_planner'],
  },
  {
    key: 'relationship-review-agent',
    title: '关系审查Agent',
    summary: '负责分析跨图引用、详图关系和图纸之间是否存在可继续审查的关联。',
    details: '主要功能：先找出值得继续核对的跨图关系，为尺寸、材料等后续审查建立图纸对照基础。',
    stageKeys: ['sheet_relationship_discovery'],
  },
  {
    key: 'index-review-agent',
    title: '索引审查Agent',
    summary: '负责对高歧义索引问题做 AI 复核，减少规则审查带来的误报。',
    details: '主要功能：在规则主判的基础上，只对存在歧义的索引问题做一次视觉复核，不替代规则主判。',
    stageKeys: ['index_visual_review'],
  },
  {
    key: 'dimension-review-agent',
    title: '尺寸审查Agent',
    summary: '负责单图尺寸语义理解、纯视觉尺寸读取和跨图尺寸对比。',
    details: '主要功能：先理解每张图中的尺寸含义，再对有关系的图纸做尺寸一致性和冲突核查。',
    stageKeys: ['dimension_single_sheet', 'dimension_visual_only', 'dimension_pair_compare'],
  },
  {
    key: 'material-review-agent',
    title: '材料审查Agent',
    summary: '负责核对材料表、图面材料标注和跨图材料一致性。',
    details: '主要功能：检查材料表与图纸使用表达是否一致，并结合关系边做跨图材料复核。',
    stageKeys: ['material_consistency_review'],
  },
];

const FALLBACK_AGENT_GROUP: PromptAgentGroup = {
  key: 'advanced-stages',
  title: '高级阶段设置',
  summary: '这里放还没有归入 Agent 视角的底层阶段。',
  details: '主要功能：保留底层阶段的直接编辑入口，避免遗漏新阶段。',
  stageKeys: [],
};

function toEditableStage(stage: AIPromptStage): EditablePromptStage {
  return {
    ...stage,
    draftSystemPrompt: stage.system_prompt,
    draftUserPrompt: stage.user_prompt,
    dirty: false,
    pendingReset: false,
    justSaved: false,
  };
}

function deriveStageDraftState(
  stage: EditablePromptStage,
  nextSystemPrompt: string,
  nextUserPrompt: string,
) {
  const matchesSaved =
    nextSystemPrompt === stage.system_prompt && nextUserPrompt === stage.user_prompt;
  const matchesDefault =
    nextSystemPrompt === stage.default_system_prompt &&
    nextUserPrompt === stage.default_user_prompt;

  return {
    draftSystemPrompt: nextSystemPrompt,
    draftUserPrompt: nextUserPrompt,
    dirty: !matchesSaved,
    pendingReset: !matchesSaved && matchesDefault,
    justSaved: false,
  };
}

function readDefaultAuditProviderMode(): AuditProviderMode {
  if (typeof window === 'undefined') return DEFAULT_AUDIT_PROVIDER_MODE;
  const raw = window.localStorage.getItem(AUDIT_PROVIDER_STORAGE_KEY);
  return raw === 'codex_sdk' ? 'codex_sdk' : DEFAULT_AUDIT_PROVIDER_MODE;
}

export default function SettingsPrompts() {
  const [stages, setStages] = useState<EditablePromptStage[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingStageKey, setSavingStageKey] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [saveMessage, setSaveMessage] = useState('');
  const [defaultAuditProviderMode, setDefaultAuditProviderMode] = useState<AuditProviderMode>(readDefaultAuditProviderMode);

  const hasUnsavedChanges = stages.some(stage => stage.dirty);
  const groupedStages = PROMPT_AGENT_GROUPS.map(group => ({
    ...group,
    stages: group.stageKeys
      .map(stageKey => stages.find(stage => stage.stage_key === stageKey))
      .filter((stage): stage is EditablePromptStage => Boolean(stage)),
  })).filter(group => group.stages.length > 0);

  const mappedStageKeys = new Set(
    PROMPT_AGENT_GROUPS.flatMap(group => group.stageKeys),
  );
  const fallbackStages = stages.filter(stage => !mappedStageKeys.has(stage.stage_key));

  const getErrorMessage = (value: unknown, fallback: string) => {
    if (axios.isAxiosError(value)) {
      if (typeof value.response?.data?.detail === 'string') return value.response.data.detail;
      return value.message || fallback;
    }
    if (value instanceof Error && value.message) return value.message;
    return fallback;
  };

  const loadStages = async () => {
    try {
      setLoading(true);
      setError('');
      const response = await api.getAIPromptSettings();
      setStages(response.stages.map(toEditableStage));
    } catch (value) {
      setError(getErrorMessage(value, '读取提示词设置失败。'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStages();
  }, []);

  useBeforeUnload(event => {
    if (!hasUnsavedChanges) return;
    event.preventDefault();
  });

  const updateStage = (stageKey: string, patch: Partial<EditablePromptStage>) => {
    setStages(current =>
      current.map(stage => (stage.stage_key === stageKey ? { ...stage, ...patch } : stage)),
    );
    setSaveMessage('');
  };

  const handlePromptChange = (
    stageKey: string,
    field: 'draftSystemPrompt' | 'draftUserPrompt',
    value: string,
  ) => {
    const stage = stages.find(item => item.stage_key === stageKey);
    if (!stage) return;
    updateStage(
      stageKey,
      deriveStageDraftState(
        stage,
        field === 'draftSystemPrompt' ? value : stage.draftSystemPrompt,
        field === 'draftUserPrompt' ? value : stage.draftUserPrompt,
      ),
    );
  };

  const handleRestoreDefault = (stageKey: string) => {
    const stage = stages.find(item => item.stage_key === stageKey);
    if (!stage) return;
    updateStage(
      stageKey,
      deriveStageDraftState(stage, stage.default_system_prompt, stage.default_user_prompt),
    );
  };

  const handleSaveAll = async () => {
    const resetTargets = stages.filter(stage => stage.dirty && stage.pendingReset);
    const updateTargets = stages
      .filter(stage => stage.dirty && !stage.pendingReset)
      .map(stage => ({
        stage_key: stage.stage_key,
        system_prompt: stage.draftSystemPrompt,
        user_prompt: stage.draftUserPrompt,
      }));

    if (resetTargets.length === 0 && updateTargets.length === 0) {
      return;
    }

    try {
      setSaving(true);
      setError('');
      setSaveMessage('');

      const tasks: Promise<unknown>[] = [];
      if (updateTargets.length > 0) {
        tasks.push(api.updateAIPromptSettings(updateTargets));
      }
      for (const stage of resetTargets) {
        tasks.push(api.resetAIPromptStage(stage.stage_key));
      }
      await Promise.all(tasks);

      const response = await api.getAIPromptSettings();
      setStages(response.stages.map(stage => ({ ...toEditableStage(stage), justSaved: true })));
      setSaveMessage('提示词已经保存，后面新发起的识别和审核都会用这套新内容。');
    } catch (value) {
      setError(getErrorMessage(value, '保存提示词失败。'));
    } finally {
      setSaving(false);
    }
  };

  const handleSaveStage = async (stageKey: string) => {
    const stage = stages.find(item => item.stage_key === stageKey);
    if (!stage || !stage.dirty) return;

    try {
      setSavingStageKey(stageKey);
      setError('');
      setSaveMessage('');

      if (stage.pendingReset) {
        await api.resetAIPromptStage(stage.stage_key);
      } else {
        await api.updateAIPromptSettings([
          {
            stage_key: stage.stage_key,
            system_prompt: stage.draftSystemPrompt,
            user_prompt: stage.draftUserPrompt,
          },
        ]);
      }

      const response = await api.getAIPromptSettings();
      setStages(response.stages.map(item => ({ ...toEditableStage(item), justSaved: item.stage_key === stageKey })));
      setSaveMessage(`"${stage.title}"已经保存，后面新发起的流程会直接用这版提示词。`);
    } catch (value) {
      setError(getErrorMessage(value, '保存提示词失败。'));
    } finally {
      setSavingStageKey(null);
    }
  };

  const handleDefaultAuditProviderChange = (next: AuditProviderMode) => {
    setDefaultAuditProviderMode(next);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(AUDIT_PROVIDER_STORAGE_KEY, next);
      window.dispatchEvent(new CustomEvent('ccad:audit-provider-default-changed', {
        detail: { providerMode: next },
      }));
    }
    setSaveMessage(`默认审核引擎已改成 ${getAuditProviderLabel(next)}，后面新发起的审核会先选这个。`);
  };

  return (
    <>
      <section className="flex items-start justify-between gap-6">
        <p className="max-w-[780px] text-[15px] leading-7 text-muted-foreground">
          这里现在按 AI Agent 来管理提示词。你改完点保存，后面新发起的目录识别、关系分析、任务规划和正式审核流程都会直接用新内容。
        </p>
        <Button
          type="button"
          className="h-11 shrink-0 rounded-none px-6 text-[14px]"
          onClick={handleSaveAll}
          disabled={saving || !hasUnsavedChanges}
        >
          {saving ? '保存中...' : '保存全部'}
        </Button>
      </section>

      <Card className="rounded-none border border-border shadow-none">
        <CardHeader>
          <CardTitle>默认审核引擎</CardTitle>
          <CardDescription>
            这里决定新发起审核时默认先选哪条路线。真正启动前，页面里还可以按这一次的需要临时切换。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AuditProviderSelector
            value={defaultAuditProviderMode}
            onChange={handleDefaultAuditProviderChange}
          />
        </CardContent>
      </Card>

      {saveMessage ? (
        <section className="border border-success/30 bg-success/10 px-5 py-4 text-[14px] text-foreground">
          {saveMessage}
        </section>
      ) : null}

      <section className="border border-primary/20 bg-primary/5 px-5 py-4 text-[14px] leading-7 text-foreground">
        这里展示的是会真正调用 AI 的 Agent。
        <span className="font-medium">证据规划器</span>
        和
        <span className="font-medium">证据服务层</span>
        不在这里配置，因为它们不是 AI Agent，而是负责证据策略和取图缓存的基础能力。
      </section>

      {error ? (
        <section className="border border-destructive/20 bg-destructive/5 px-5 py-4 text-[14px] text-foreground">
          {error}
        </section>
      ) : null}

      {loading ? (
        <section className="border border-border bg-secondary px-5 py-10 text-[15px] text-muted-foreground">
          正在读取提示词设置...
        </section>
      ) : (
        <section className="flex flex-col gap-6">
          {groupedStages.map(group => (
            <Card key={group.key} className="rounded-none border border-border shadow-none">
              <CardHeader className="gap-3 border-b border-border/80 pb-5">
                <CardTitle className="text-[24px] font-semibold text-foreground">{group.title}</CardTitle>
                <CardDescription className="max-w-[980px] text-[14px] leading-7 text-muted-foreground">
                  {group.summary}
                </CardDescription>
                <div className="border-l-2 border-primary pl-3 text-[13px] leading-6 text-foreground">
                  {group.details}
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-6 pt-6">
                {group.stages.map(stage => {
                  const stateLabel = stage.dirty ? '未保存' : stage.justSaved ? '已保存' : '';
                  const isSavingThisStage = savingStageKey === stage.stage_key;

                  return (
                    <section
                      key={stage.stage_key}
                      className="rounded-none border border-border/80 bg-secondary/20"
                    >
                      <div className="border-b border-border/80 px-6 py-5">
                        <div className="flex items-start justify-between gap-6">
                          <div className="space-y-3">
                            <div className="flex flex-wrap items-center gap-3">
                              <div className="text-[20px] font-semibold text-foreground">{stage.title}</div>
                              <Badge variant="outline" className="rounded-none">
                                stage: {stage.stage_key}
                              </Badge>
                            </div>
                            <div className="max-w-[920px] text-[14px] leading-7 text-muted-foreground">
                              {stage.description}
                            </div>
                            <div className="inline-flex flex-wrap items-center gap-3 text-[13px] text-muted-foreground">
                              <span className="border-l-2 border-primary pl-3 text-foreground">
                                当前调用位置：{stage.call_site}
                              </span>
                            </div>
                          </div>
                          <div className="flex shrink-0 items-center gap-3">
                            {stateLabel ? (
                              <Badge
                                variant={statusTone[stage.dirty ? 'dirty' : stage.justSaved ? 'saved' : 'default']}
                                className="rounded-none"
                              >
                                {stateLabel}
                              </Badge>
                            ) : null}
                            <Button
                              type="button"
                              variant="outline"
                              className="rounded-none"
                              onClick={() => handleRestoreDefault(stage.stage_key)}
                            >
                              恢复默认
                            </Button>
                            <Button
                              type="button"
                              className="rounded-none"
                              onClick={() => handleSaveStage(stage.stage_key)}
                              disabled={saving || isSavingThisStage || !stage.dirty}
                            >
                              {isSavingThisStage ? '保存中...' : '保存'}
                            </Button>
                          </div>
                        </div>
                        {stage.placeholders.length > 0 ? (
                          <div className="mt-4 rounded-none border border-primary/20 bg-primary/5 px-4 py-3 text-[13px] leading-6 text-foreground">
                            可用变量：{stage.placeholders.map(item => `{{${item}}}`).join('、')}
                          </div>
                        ) : null}
                      </div>
                      <div className="grid gap-6 px-6 py-6 lg:grid-cols-2">
                        <div className="space-y-3">
                          <div className="text-[13px] font-medium tracking-wide text-muted-foreground">
                            System Prompt
                          </div>
                          <textarea
                            value={stage.draftSystemPrompt}
                            onChange={event =>
                              handlePromptChange(stage.stage_key, 'draftSystemPrompt', event.target.value)
                            }
                            className={`${textareaClassName} rounded-none`}
                          />
                        </div>
                        <div className="space-y-3">
                          <div className="text-[13px] font-medium tracking-wide text-muted-foreground">
                            User Prompt
                          </div>
                          <textarea
                            value={stage.draftUserPrompt}
                            onChange={event =>
                              handlePromptChange(stage.stage_key, 'draftUserPrompt', event.target.value)
                            }
                            className={`${textareaClassName} rounded-none`}
                          />
                        </div>
                      </div>
                    </section>
                  );
                })}
              </CardContent>
            </Card>
          ))}

          {fallbackStages.length > 0 ? (
            <Card className="rounded-none border border-border shadow-none">
              <CardHeader className="gap-3 border-b border-border/80 pb-5">
                <CardTitle className="text-[24px] font-semibold text-foreground">
                  {FALLBACK_AGENT_GROUP.title}
                </CardTitle>
                <CardDescription className="max-w-[980px] text-[14px] leading-7 text-muted-foreground">
                  {FALLBACK_AGENT_GROUP.summary}
                </CardDescription>
                <div className="border-l-2 border-primary pl-3 text-[13px] leading-6 text-foreground">
                  {FALLBACK_AGENT_GROUP.details}
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-6 pt-6">
                {fallbackStages.map(stage => {
                  const stateLabel = stage.dirty ? '未保存' : stage.justSaved ? '已保存' : '';
                  const isSavingThisStage = savingStageKey === stage.stage_key;

                  return (
                    <section
                      key={stage.stage_key}
                      className="rounded-none border border-border/80 bg-secondary/20"
                    >
                      <div className="border-b border-border/80 px-6 py-5">
                        <div className="flex items-start justify-between gap-6">
                          <div className="space-y-3">
                            <div className="flex flex-wrap items-center gap-3">
                              <div className="text-[20px] font-semibold text-foreground">{stage.title}</div>
                              <Badge variant="outline" className="rounded-none">
                                stage: {stage.stage_key}
                              </Badge>
                            </div>
                            <div className="max-w-[920px] text-[14px] leading-7 text-muted-foreground">
                              {stage.description}
                            </div>
                            <div className="inline-flex flex-wrap items-center gap-3 text-[13px] text-muted-foreground">
                              <span className="border-l-2 border-primary pl-3 text-foreground">
                                当前调用位置：{stage.call_site}
                              </span>
                            </div>
                          </div>
                          <div className="flex shrink-0 items-center gap-3">
                            {stateLabel ? (
                              <Badge
                                variant={statusTone[stage.dirty ? 'dirty' : stage.justSaved ? 'saved' : 'default']}
                                className="rounded-none"
                              >
                                {stateLabel}
                              </Badge>
                            ) : null}
                            <Button
                              type="button"
                              variant="outline"
                              className="rounded-none"
                              onClick={() => handleRestoreDefault(stage.stage_key)}
                            >
                              恢复默认
                            </Button>
                            <Button
                              type="button"
                              className="rounded-none"
                              onClick={() => handleSaveStage(stage.stage_key)}
                              disabled={saving || isSavingThisStage || !stage.dirty}
                            >
                              {isSavingThisStage ? '保存中...' : '保存'}
                            </Button>
                          </div>
                        </div>
                      </div>
                      <div className="grid gap-6 px-6 py-6 lg:grid-cols-2">
                        <div className="space-y-3">
                          <div className="text-[13px] font-medium tracking-wide text-muted-foreground">
                            System Prompt
                          </div>
                          <textarea
                            value={stage.draftSystemPrompt}
                            onChange={event =>
                              handlePromptChange(stage.stage_key, 'draftSystemPrompt', event.target.value)
                            }
                            className={`${textareaClassName} rounded-none`}
                          />
                        </div>
                        <div className="space-y-3">
                          <div className="text-[13px] font-medium tracking-wide text-muted-foreground">
                            User Prompt
                          </div>
                          <textarea
                            value={stage.draftUserPrompt}
                            onChange={event =>
                              handlePromptChange(stage.stage_key, 'draftUserPrompt', event.target.value)
                            }
                            className={`${textareaClassName} rounded-none`}
                          />
                        </div>
                      </div>
                    </section>
                  );
                })}
              </CardContent>
            </Card>
          ) : null}
        </section>
      )}
    </>
  );
}
