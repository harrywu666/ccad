import { useEffect, useState } from 'react';
import { useBeforeUnload } from 'react-router-dom';
import axios from 'axios';
import * as api from '@/api';
import type { AIPromptStage } from '@/types/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import SettingsFileEditorDialog from './SettingsFileEditorDialog';

type EditablePromptStage = AIPromptStage & {
  draftSystemPrompt: string;
  draftUserPrompt: string;
  dirty: boolean;
  pendingReset: boolean;
  justSaved: boolean;
};

type PromptAgentGroup = {
  key: string;
  title: string;
  summary: string;
  details: string;
  stageKeys: string[];
};

const statusTone: Record<string, 'outline' | 'warning' | 'success'> = {
  default: 'outline',
  dirty: 'warning',
  saved: 'success',
};

const PROMPT_AGENT_GROUPS: PromptAgentGroup[] = [
  {
    key: 'drawing-recognition-agent',
    title: '图纸识别阶段',
    summary: '负责目录识别、图纸识别、识别结果汇总和目录匹配校验。',
    details: '这部分还是按旧 stage 模板运行，影响目录识别和图纸识别链路。',
    stageKeys: [
      'catalog_recognition',
      'sheet_recognition',
      'sheet_summarization',
      'sheet_catalog_validation',
    ],
  },
  {
    key: 'master-planner-agent',
    title: '总控规划阶段',
    summary: '负责先看全局上下文，决定后面要查哪些图、哪些图之间要互相对照。',
    details: '这部分还没完全并入新的 Agent 文件体系，仍然直接影响任务规划结果。',
    stageKeys: ['master_task_planner'],
  },
  {
    key: 'relationship-review-agent',
    title: '关系审查阶段',
    summary: '负责分析跨图引用、详图关系和图纸之间是否存在可继续审查的关联。',
    details: '这部分还是旧的运行时模板，直接影响跨图关系发现。',
    stageKeys: ['sheet_relationship_discovery'],
  },
  {
    key: 'index-review-agent',
    title: '索引审查阶段',
    summary: '负责对高歧义索引问题做 AI 复核，减少规则审查带来的误报。',
    details: '这部分仍然走 stage 模板，不是 review_worker skill 文件本身。',
    stageKeys: ['index_visual_review'],
  },
  {
    key: 'dimension-review-agent',
    title: '尺寸审查阶段',
    summary: '负责单图尺寸语义理解、纯视觉尺寸读取和跨图尺寸对比。',
    details: '这部分还在旧模板层，后续会逐步往新的 Agent / Skill 架构里收。',
    stageKeys: ['dimension_single_sheet', 'dimension_visual_only', 'dimension_pair_compare'],
  },
  {
    key: 'material-review-agent',
    title: '材料审查阶段',
    summary: '负责核对材料表、图面材料标注和跨图材料一致性。',
    details: '这部分仍然直接影响材料审核的运行时模板。',
    stageKeys: ['material_consistency_review'],
  },
];

const FALLBACK_AGENT_GROUP: PromptAgentGroup = {
  key: 'advanced-stages',
  title: '其他旧版阶段',
  summary: '这里放还没有整理进 Agent 视角的底层阶段。',
  details: '这部分是兼容兜底区，避免有旧模板漏管。',
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

function getErrorMessage(value: unknown, fallback: string) {
  if (axios.isAxiosError(value)) {
    if (typeof value.response?.data?.detail === 'string') return value.response.data.detail;
    return value.message || fallback;
  }
  if (value instanceof Error && value.message) return value.message;
  return fallback;
}

export default function SettingsLegacyStagePrompts() {
  const [stages, setStages] = useState<EditablePromptStage[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingStageKey, setSavingStageKey] = useState<string | null>(null);
  const [activeEditor, setActiveEditor] = useState<{
    stageKey: string;
    field: 'draftSystemPrompt' | 'draftUserPrompt';
  } | null>(null);
  const [error, setError] = useState('');
  const [saveMessage, setSaveMessage] = useState('');
  const hasUnsavedChanges = stages.some(stage => stage.dirty);

  const groupedStages = PROMPT_AGENT_GROUPS.map(group => ({
    ...group,
    stages: group.stageKeys
      .map(stageKey => stages.find(stage => stage.stage_key === stageKey))
      .filter((stage): stage is EditablePromptStage => Boolean(stage)),
  })).filter(group => group.stages.length > 0);

  const mappedStageKeys = new Set(PROMPT_AGENT_GROUPS.flatMap(group => group.stageKeys));
  const fallbackStages = stages.filter(stage => !mappedStageKeys.has(stage.stage_key));

  const loadStages = async () => {
    try {
      setLoading(true);
      setError('');
      const response = await api.getAIPromptSettings();
      setStages(response.stages.map(toEditableStage));
    } catch (value) {
      setError(getErrorMessage(value, '读取旧版阶段设置失败。'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadStages();
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

    if (resetTargets.length === 0 && updateTargets.length === 0) return;

    try {
      setSaving(true);
      setError('');
      setSaveMessage('');

      const tasks: Promise<unknown>[] = [];
      if (updateTargets.length > 0) tasks.push(api.updateAIPromptSettings(updateTargets));
      for (const stage of resetTargets) {
        tasks.push(api.resetAIPromptStage(stage.stage_key));
      }
      await Promise.all(tasks);

      const response = await api.getAIPromptSettings();
      setStages(response.stages.map(stage => ({ ...toEditableStage(stage), justSaved: true })));
      setSaveMessage('旧版阶段模板已经保存，后面新发起的旧链路运行会直接用这版内容。');
    } catch (value) {
      setError(getErrorMessage(value, '保存旧版阶段设置失败。'));
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
      setStages(
        response.stages.map(item => ({
          ...toEditableStage(item),
          justSaved: item.stage_key === stageKey,
        })),
      );
      setSaveMessage(`"${stage.title}" 已保存，后面旧链路会直接用这版阶段模板。`);
    } catch (value) {
      setError(getErrorMessage(value, '保存旧版阶段设置失败。'));
    } finally {
      setSavingStageKey(null);
    }
  };

  const activeStage = activeEditor
    ? stages.find(stage => stage.stage_key === activeEditor.stageKey) ?? null
    : null;

  const renderStageCard = (stage: EditablePromptStage) => {
    const stateLabel = stage.dirty ? '未保存' : stage.justSaved ? '已保存' : '';

    return (
      <section
        key={stage.stage_key}
        className="h-full rounded-none border border-border/80 bg-secondary/20 px-5 py-5"
      >
        <div className="flex h-full flex-col gap-4">
          <div className="flex-1 space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <div className="text-[18px] font-semibold text-foreground">{stage.title}</div>
              <Badge variant="outline" className="rounded-none">
                stage: {stage.stage_key}
              </Badge>
              {stateLabel ? (
                <Badge
                  variant={statusTone[stage.dirty ? 'dirty' : stage.justSaved ? 'saved' : 'default']}
                  className="rounded-none"
                >
                  {stateLabel}
                </Badge>
              ) : null}
            </div>
            <div className="text-[14px] leading-7 text-muted-foreground">
              {stage.description}
            </div>
            <div className="border-l-2 border-primary pl-3 text-[13px] leading-6 text-foreground">
              当前调用位置：{stage.call_site}
            </div>
            {stage.placeholders.length > 0 ? (
              <div className="rounded-none border border-primary/20 bg-primary/5 px-4 py-3 text-[13px] leading-6 text-foreground">
                可用变量：{stage.placeholders.map(item => `{{${item}}}`).join('、')}
              </div>
            ) : null}
          </div>
          <div className="mt-auto flex flex-wrap gap-3">
            <Button
              type="button"
              className="rounded-none"
              onClick={() => setActiveEditor({ stageKey: stage.stage_key, field: 'draftSystemPrompt' })}
            >
              编辑 System Prompt
            </Button>
            <Button
              type="button"
              variant="outline"
              className="rounded-none"
              onClick={() => setActiveEditor({ stageKey: stage.stage_key, field: 'draftUserPrompt' })}
            >
              编辑 User Prompt
            </Button>
          </div>
        </div>
      </section>
    );
  };

  return (
    <section className="flex flex-col gap-6">
      <section className="flex items-start justify-between gap-6 border border-primary/20 bg-primary/5 px-5 py-4 text-[14px] leading-7 text-foreground">
        <p className="max-w-[980px]">
          这部分还是旧的运行时阶段模板，不是新的 Agent md 文件。
          它现在仍然真实生效，所以先放在兼容层里，等后面逐步收编进新架构再下线。
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
          正在读取旧版阶段设置...
        </section>
      ) : (
        <>
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
              <CardContent className="grid gap-4 pt-6 md:grid-cols-2">
                {group.stages.map(renderStageCard)}
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
              <CardContent className="grid gap-4 pt-6 md:grid-cols-2">
                {fallbackStages.map(renderStageCard)}
              </CardContent>
            </Card>
          ) : null}
        </>
      )}

      {activeStage && activeEditor ? (
        <SettingsFileEditorDialog
          open={Boolean(activeStage && activeEditor)}
          onOpenChange={open => {
            if (!open) setActiveEditor(null);
          }}
          title={`${activeStage.title} · ${activeEditor.field === 'draftSystemPrompt' ? 'System Prompt' : 'User Prompt'}`}
          description={`${activeStage.description} 当前调用位置：${activeStage.call_site}`}
          fileLabel={activeStage.stage_key}
          statusLabel={activeStage.dirty ? '未保存' : activeStage.justSaved ? '已保存' : undefined}
          statusTone={activeStage.justSaved ? 'success' : 'warning'}
          value={
            activeEditor.field === 'draftSystemPrompt'
              ? activeStage.draftSystemPrompt
              : activeStage.draftUserPrompt
          }
          onChange={value => handlePromptChange(activeStage.stage_key, activeEditor.field, value)}
          onSave={async () => {
            await handleSaveStage(activeStage.stage_key);
          }}
          saveDisabled={!activeStage.dirty}
          saving={savingStageKey === activeStage.stage_key}
          onRestoreDefault={() => handleRestoreDefault(activeStage.stage_key)}
          restoreDisabled={!activeStage.dirty && !activeStage.pendingReset}
        />
      ) : null}
    </section>
  );
}
