import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import * as api from '@/api';
import type { ReviewWorkerSkillAsset } from '@/types/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import SettingsFileEditorDialog from './SettingsFileEditorDialog';

type EditableSkill = ReviewWorkerSkillAsset & {
  draftContent: string;
  dirty: boolean;
  justSaved: boolean;
};

const textareaClassName =
  'min-h-[220px] w-full resize-y border border-border bg-secondary px-4 py-4 text-[14px] leading-7 text-foreground outline-none transition-colors focus:border-primary';

function toEditableSkill(item: ReviewWorkerSkillAsset): EditableSkill {
  return {
    ...item,
    draftContent: item.content,
    dirty: false,
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

export default function SettingsReviewWorkerSkills() {
  const [items, setItems] = useState<EditableSkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [saveMessage, setSaveMessage] = useState('');

  const hasUnsavedChanges = useMemo(() => items.some(item => item.dirty), [items]);

  const loadItems = async () => {
    try {
      setLoading(true);
      setError('');
      const response = await api.getReviewWorkerSkillAssets();
      setItems(response.items.map(toEditableSkill));
    } catch (value) {
      setError(getErrorMessage(value, '读取 review_worker skills 失败。'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadItems();
  }, []);

  const updateItem = (key: string, patch: Partial<EditableSkill>) => {
    setItems(current => current.map(item => (item.key === key ? { ...item, ...patch } : item)));
    setSaveMessage('');
  };

  const handleContentChange = (key: string, value: string) => {
    const current = items.find(item => item.key === key);
    if (!current) return;
    updateItem(key, {
      draftContent: value,
      dirty: value !== current.content,
      justSaved: false,
    });
  };

  const handleSave = async (key?: string) => {
    const targetItems = items.filter(item => item.dirty && (!key || item.key === key));
    if (targetItems.length === 0) return;

    try {
      setError('');
      setSaveMessage('');
      setSaving(!key);
      setSavingKey(key || null);
      const response = await api.updateReviewWorkerSkillAssets(
        targetItems.map(item => ({
          key: item.key,
          content: item.draftContent,
        })),
      );
      setItems(response.items.map(item => ({
        ...toEditableSkill(item),
        justSaved: !key || item.key === key,
      })));
      setSaveMessage(
        key
          ? `"${items.find(item => item.key === key)?.title || key}" 已保存，后面新的 review_worker 会直接用这版 skill。`
          : 'review_worker skills 已保存，后面新的 review_worker 会直接用这版 skill。',
      );
    } catch (value) {
      setError(getErrorMessage(value, '保存 review_worker skill 失败。'));
    } finally {
      setSaving(false);
      setSavingKey(null);
    }
  };

  const activeItem = activeKey ? items.find(item => item.key === activeKey) ?? null : null;

  return (
    <section className="flex flex-col gap-6 rounded-none border border-border/80 bg-background">
      <div className="border-b border-border/80 px-6 py-5">
        <div className="flex items-start justify-between gap-6">
          <div className="space-y-3">
            <div className="text-[20px] font-semibold text-foreground">Worker Skills</div>
            <div className="max-w-[920px] text-[14px] leading-7 text-muted-foreground">
              这里是副审 Worker 真正调用的能力说明文件。每个 skill 都对应一个具体的核查能力，而不是旧的 stage prompt。
            </div>
            <div className="border-l-2 border-primary pl-3 text-[13px] leading-6 text-foreground">
              目前这里先放已经 skill 化的能力文件，后面新增 skill 会继续往这里加。
            </div>
          </div>
          <Button
            type="button"
            className="h-11 shrink-0 rounded-none px-6 text-[14px]"
            onClick={() => void handleSave()}
            disabled={saving || !hasUnsavedChanges}
          >
            {saving ? '保存中...' : '保存全部'}
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-6 px-6 py-6">
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
            正在读取 review_worker skills...
          </section>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
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
      </div>

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
          onChange={value => handleContentChange(activeItem.key, value)}
          onSave={async () => {
            await handleSave(activeItem.key);
          }}
          saveDisabled={!activeItem.dirty}
          saving={savingKey === activeItem.key}
        />
      ) : null}
    </section>
  );
}
