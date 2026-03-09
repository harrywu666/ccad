import { useEffect, useState } from 'react';
import { useBeforeUnload } from 'react-router-dom';
import axios from 'axios';
import * as api from '@/api';
import type { AIPromptStage } from '@/types/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

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

export default function SettingsPrompts() {
  const [stages, setStages] = useState<EditablePromptStage[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingStageKey, setSavingStageKey] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [saveMessage, setSaveMessage] = useState('');

  const hasUnsavedChanges = stages.some(stage => stage.dirty);

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

  return (
    <>
      <section className="flex items-start justify-between gap-6">
        <p className="max-w-[780px] text-[15px] leading-7 text-muted-foreground">
          这里可以直接改系统当前在用的 AI 提示词。你改完点保存，后面新发起的目录识别、图纸识别、AI 图纸关系发现、任务预规划和正式审核流程都会立刻用新内容。
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

      <section className="border border-primary/20 bg-primary/5 px-5 py-4 text-[14px] leading-7 text-foreground">
        预规划相关阶段现在分成两段生效：
        <span className="font-medium">“图纸关系发现”</span>
        负责先找跨图引用，
        <span className="font-medium">“总控任务规划”</span>
        再基于这些关系生成任务图。设置页里改这两段后，`/audit/tasks/plan` 和正式 `开始审核` 都会使用同一套新提示词。
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
          {stages.map(stage => {
            const stateLabel = stage.dirty ? '未保存' : stage.justSaved ? '已保存' : '';
            const isSavingThisStage = savingStageKey === stage.stage_key;

            return (
              <Card key={stage.stage_key} className="rounded-none border border-border shadow-none">
                <CardHeader className="gap-4 border-b border-border/80 pb-5">
                  <div className="flex items-start justify-between gap-6">
                    <div className="space-y-3">
                      <CardTitle className="text-[22px] font-semibold text-foreground">{stage.title}</CardTitle>
                      <CardDescription className="max-w-[920px] text-[14px] leading-7 text-muted-foreground">
                        {stage.description}
                      </CardDescription>
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
                    <div className="rounded-none border border-primary/20 bg-primary/5 px-4 py-3 text-[13px] leading-6 text-foreground">
                      可用变量：{stage.placeholders.map(item => `{{${item}}}`).join('、')}
                    </div>
                  ) : null}
                </CardHeader>
                <CardContent className="grid gap-6 pt-6 lg:grid-cols-2">
                  <div className="space-y-3">
                    <div className="text-[13px] font-medium tracking-wide text-muted-foreground">角色设定</div>
                    <textarea
                      value={stage.draftSystemPrompt}
                      onChange={event => handlePromptChange(stage.stage_key, 'draftSystemPrompt', event.target.value)}
                      className={`${textareaClassName} rounded-none`}
                    />
                  </div>
                  <div className="space-y-3">
                    <div className="text-[13px] font-medium tracking-wide text-muted-foreground">执行指令</div>
                    <textarea
                      value={stage.draftUserPrompt}
                      onChange={event => handlePromptChange(stage.stage_key, 'draftUserPrompt', event.target.value)}
                      className={`${textareaClassName} rounded-none`}
                    />
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </section>
      )}
    </>
  );
}
