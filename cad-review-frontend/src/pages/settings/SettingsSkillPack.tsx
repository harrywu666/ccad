import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import * as api from '@/api';
import type { SkillPackItem, SkillTypeItem } from '@/types/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

type DraftState = {
  id?: string;
  skillType: string;
  title: string;
  content: string;
  priority: number;
  stageKeys: string[];
};

const SOURCE_LABEL: Record<string, string> = {
  manual: '手动',
  auto: '自动',
};

const MODE_LABEL: Record<string, string> = {
  code: '代码',
  ai: 'AI',
  hybrid: '混合',
};

function createDraft(skillType: string, item?: SkillPackItem): DraftState {
  return {
    id: item?.id,
    skillType,
    title: item?.title || '',
    content: item?.content || '',
    priority: item?.priority ?? 100,
    stageKeys: item?.stage_keys || [],
  };
}

export default function SettingsSkillPack() {
  const [skillTypes, setSkillTypes] = useState<SkillTypeItem[]>([]);
  const [items, setItems] = useState<SkillPackItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [savingKey, setSavingKey] = useState('');
  const [draft, setDraft] = useState<DraftState | null>(null);

  const getErrorMessage = (value: unknown, fallback: string) => {
    if (axios.isAxiosError(value)) {
      if (typeof value.response?.data?.detail === 'string') return value.response.data.detail;
      return value.message || fallback;
    }
    if (value instanceof Error && value.message) return value.message;
    return fallback;
  };

  const loadData = async () => {
    try {
      setLoading(true);
      setError('');
      const [typeRes, listRes] = await Promise.all([api.getSkillTypes(), api.getSkillPacks()]);
      setSkillTypes(typeRes.items);
      setItems(listRes.items);
    } catch (value) {
      setError(getErrorMessage(value, '读取审查技能包失败。'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  const itemsByType = useMemo(() => {
    return skillTypes.map(type => ({
      type,
      items: items.filter(item => item.skill_type === type.skill_type),
    }));
  }, [items, skillTypes]);

  const handleToggle = async (item: SkillPackItem, nextActive: boolean) => {
    try {
      setSavingKey(item.id);
      setError('');
      await api.toggleSkillPack(item.id, nextActive);
      await loadData();
    } catch (value) {
      setError(getErrorMessage(value, '更新规则启用状态失败。'));
    } finally {
      setSavingKey('');
    }
  };

  const handleDelete = async (item: SkillPackItem) => {
    try {
      setSavingKey(item.id);
      setError('');
      await api.deleteSkillPack(item.id);
      setDraft(current => (current?.id === item.id ? null : current));
      setMessage(`已删除“${item.title}”。`);
      await loadData();
    } catch (value) {
      setError(getErrorMessage(value, '删除规则失败。'));
    } finally {
      setSavingKey('');
    }
  };

  const handleSave = async () => {
    if (!draft) return;
    try {
      setSavingKey(draft.id || `new:${draft.skillType}`);
      setError('');
      setMessage('');
      if (draft.id) {
        await api.updateSkillPack(draft.id, {
          title: draft.title,
          content: draft.content,
          priority: draft.priority,
          stage_keys: draft.stageKeys,
        });
        setMessage(`已更新“${draft.title}”。`);
      } else {
        await api.createSkillPack({
          skill_type: draft.skillType,
          title: draft.title,
          content: draft.content,
          priority: draft.priority,
          stage_keys: draft.stageKeys,
        });
        setMessage(`已新增“${draft.title}”。`);
      }
      setDraft(null);
      await loadData();
    } catch (value) {
      setError(getErrorMessage(value, '保存规则失败。'));
    } finally {
      setSavingKey('');
    }
  };

  const updateDraft = (patch: Partial<DraftState>) => {
    setDraft(current => (current ? { ...current, ...patch } : current));
  };

  return (
    <>
      <p className="max-w-[900px] text-[15px] leading-7 text-muted-foreground">
        审查技能包决定系统在审图时会参考哪些知识。索引规则进入代码审核链路，尺寸与材料规则进入 AI 审核链路。
      </p>

      {message ? (
        <section className="border border-success/30 bg-success/10 px-5 py-4 text-[14px] text-foreground">
          {message}
        </section>
      ) : null}

      {error ? (
        <section className="border border-destructive/20 bg-destructive/5 px-5 py-4 text-[14px] text-foreground">
          {error}
        </section>
      ) : null}

      {loading ? (
        <section className="border border-border bg-secondary px-5 py-10 text-[15px] text-muted-foreground">
          正在读取审查技能包...
        </section>
      ) : (
        <section className="flex flex-col gap-6">
          {itemsByType.map(({ type, items: groupedItems }) => {
            const activeCount = groupedItems.filter(item => item.is_active).length;
            const isCreating = draft?.id === undefined && draft?.skillType === type.skill_type;

            return (
              <Card key={type.skill_type} className="rounded-none border border-border shadow-none">
                <CardHeader className="border-b border-border/80 pb-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="space-y-2">
                      <CardTitle className="text-[22px] font-semibold text-foreground">
                        {type.label}
                      </CardTitle>
                      <div className="flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
                        <span>{activeCount} 条规则已启用</span>
                        <Badge variant="outline" className="rounded-none">
                          {MODE_LABEL[type.execution_mode] || type.execution_mode}
                        </Badge>
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      className="rounded-none"
                      onClick={() => setDraft(createDraft(type.skill_type))}
                    >
                      + 添加规则
                    </Button>
                  </div>
                </CardHeader>

                <CardContent className="space-y-4 p-0">
                  {groupedItems.map(item => {
                    const isEditing = draft?.id === item.id;
                    return (
                      <div key={item.id} className="border-b border-border/60 px-5 py-4 last:border-b-0">
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0 flex-1 space-y-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <label className="inline-flex items-center gap-2 text-[13px]">
                                <input
                                  type="checkbox"
                                  checked={item.is_active}
                                  disabled={savingKey === item.id}
                                  onChange={e => void handleToggle(item, e.target.checked)}
                                />
                                <span className="font-medium text-foreground">{item.title}</span>
                              </label>
                              <Badge variant="outline" className="rounded-none">
                                {SOURCE_LABEL[item.source] || item.source}
                              </Badge>
                              <Badge variant="outline" className="rounded-none">
                                {MODE_LABEL[item.execution_mode] || item.execution_mode}
                              </Badge>
                            </div>
                            <p className="line-clamp-2 text-[14px] leading-7 text-muted-foreground">
                              {item.content}
                            </p>
                            {item.stage_keys.length > 0 ? (
                              <div className="flex flex-wrap gap-2">
                                {item.stage_keys.map(stageKey => (
                                  <Badge key={stageKey} variant="outline" className="rounded-none text-[11px]">
                                    {stageKey}
                                  </Badge>
                                ))}
                              </div>
                            ) : null}
                          </div>
                          <div className="flex items-center gap-2">
                            <Button
                              type="button"
                              variant="outline"
                              className="rounded-none"
                              onClick={() => setDraft(createDraft(type.skill_type, item))}
                            >
                              编辑
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              className="rounded-none text-destructive hover:bg-destructive/10 hover:text-destructive"
                              onClick={() => void handleDelete(item)}
                            >
                              删除
                            </Button>
                          </div>
                        </div>

                        {isEditing && draft ? (
                          <div className="mt-4 space-y-3 border border-border bg-secondary/60 p-4">
                            <input
                              value={draft.title}
                              onChange={e => updateDraft({ title: e.target.value })}
                              placeholder="规则标题"
                              className="h-10 w-full border border-border bg-background px-3 text-[14px] text-foreground outline-none focus:border-primary"
                            />
                            <textarea
                              value={draft.content}
                              onChange={e => updateDraft({ content: e.target.value })}
                              placeholder="规则内容"
                              className="min-h-[120px] w-full border border-border bg-background px-3 py-3 text-[14px] leading-7 text-foreground outline-none focus:border-primary"
                            />
                            <div className="grid gap-3 md:grid-cols-2">
                              <label className="space-y-2 text-[13px] text-muted-foreground">
                                <span>优先级</span>
                                <input
                                  type="number"
                                  value={draft.priority}
                                  onChange={e => updateDraft({ priority: Number(e.target.value) || 0 })}
                                  className="h-10 w-full border border-border bg-background px-3 text-[14px] text-foreground outline-none focus:border-primary"
                                />
                              </label>
                              <div className="space-y-2 text-[13px] text-muted-foreground">
                                <span>生效 stage</span>
                                {type.allowed_stages.length > 0 ? (
                                  <div className="flex flex-col gap-2 border border-border bg-background px-3 py-3">
                                    {type.allowed_stages.map(stage => (
                                      <label key={stage.stage_key} className="inline-flex items-center gap-2 text-foreground">
                                        <input
                                          type="checkbox"
                                          checked={draft.stageKeys.includes(stage.stage_key)}
                                          onChange={e =>
                                            updateDraft({
                                              stageKeys: e.target.checked
                                                ? [...draft.stageKeys, stage.stage_key]
                                                : draft.stageKeys.filter(item => item !== stage.stage_key),
                                            })
                                          }
                                        />
                                        <span>{stage.title}</span>
                                      </label>
                                    ))}
                                  </div>
                                ) : (
                                  <div className="border border-border bg-background px-3 py-3 text-muted-foreground">
                                    当前类型没有可选的 AI stage。
                                  </div>
                                )}
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              <Button
                                type="button"
                                className="rounded-none"
                                disabled={savingKey === item.id}
                                onClick={() => void handleSave()}
                              >
                                保存
                              </Button>
                              <Button
                                type="button"
                                variant="outline"
                                className="rounded-none"
                                onClick={() => setDraft(null)}
                              >
                                取消
                              </Button>
                            </div>
                          </div>
                        ) : null}
                      </div>
                    );
                  })}

                  {isCreating && draft ? (
                    <div className="px-5 py-4">
                      <div className="space-y-3 border border-border bg-secondary/60 p-4">
                        <input
                          value={draft.title}
                          onChange={e => updateDraft({ title: e.target.value })}
                          placeholder="规则标题"
                          className="h-10 w-full border border-border bg-background px-3 text-[14px] text-foreground outline-none focus:border-primary"
                        />
                        <textarea
                          value={draft.content}
                          onChange={e => updateDraft({ content: e.target.value })}
                          placeholder="规则内容"
                          className="min-h-[120px] w-full border border-border bg-background px-3 py-3 text-[14px] leading-7 text-foreground outline-none focus:border-primary"
                        />
                        <div className="grid gap-3 md:grid-cols-2">
                          <label className="space-y-2 text-[13px] text-muted-foreground">
                            <span>优先级</span>
                            <input
                              type="number"
                              value={draft.priority}
                              onChange={e => updateDraft({ priority: Number(e.target.value) || 0 })}
                              className="h-10 w-full border border-border bg-background px-3 text-[14px] text-foreground outline-none focus:border-primary"
                            />
                          </label>
                          <div className="space-y-2 text-[13px] text-muted-foreground">
                            <span>生效 stage</span>
                            {type.allowed_stages.length > 0 ? (
                              <div className="flex flex-col gap-2 border border-border bg-background px-3 py-3">
                                {type.allowed_stages.map(stage => (
                                  <label key={stage.stage_key} className="inline-flex items-center gap-2 text-foreground">
                                    <input
                                      type="checkbox"
                                      checked={draft.stageKeys.includes(stage.stage_key)}
                                      onChange={e =>
                                        updateDraft({
                                          stageKeys: e.target.checked
                                            ? [...draft.stageKeys, stage.stage_key]
                                            : draft.stageKeys.filter(item => item !== stage.stage_key),
                                        })
                                      }
                                    />
                                    <span>{stage.title}</span>
                                  </label>
                                ))}
                              </div>
                            ) : (
                              <div className="border border-border bg-background px-3 py-3 text-muted-foreground">
                                当前类型没有可选的 AI stage。
                              </div>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <Button
                            type="button"
                            className="rounded-none"
                            disabled={savingKey === `new:${type.skill_type}`}
                            onClick={() => void handleSave()}
                          >
                            保存
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            className="rounded-none"
                            onClick={() => setDraft(null)}
                          >
                            取消
                          </Button>
                        </div>
                      </div>
                    </div>
                  ) : null}

                  {groupedItems.length === 0 && !isCreating ? (
                    <div className="px-5 py-6 text-[14px] text-muted-foreground">
                      这个类型还没有规则。
                    </div>
                  ) : null}
                </CardContent>
              </Card>
            );
          })}
        </section>
      )}
    </>
  );
}
