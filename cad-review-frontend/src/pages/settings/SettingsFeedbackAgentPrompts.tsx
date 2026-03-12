import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import * as api from '@/api';
import type { FeedbackAgentPromptAsset } from '@/types/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import SettingsFileEditorDialog from './SettingsFileEditorDialog';

type EditableAsset = FeedbackAgentPromptAsset & {
  draftContent: string;
  dirty: boolean;
  justSaved: boolean;
};

const textareaClassName =
  'min-h-[220px] w-full resize-y border border-border bg-secondary px-4 py-4 text-[14px] leading-7 text-foreground outline-none transition-colors focus:border-primary';

function toEditableAsset(item: FeedbackAgentPromptAsset): EditableAsset {
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

export default function SettingsFeedbackAgentPrompts() {
  const [items, setItems] = useState<EditableAsset[]>([]);
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
      const response = await api.getFeedbackAgentPromptAssets();
      setItems(response.items.map(toEditableAsset));
    } catch (value) {
      setError(getErrorMessage(value, '读取误报反馈 Agent 文件失败。'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadItems();
  }, []);

  const updateItem = (key: EditableAsset['key'], patch: Partial<EditableAsset>) => {
    setItems(current => current.map(item => (item.key === key ? { ...item, ...patch } : item)));
    setSaveMessage('');
  };

  const handleContentChange = (key: EditableAsset['key'], value: string) => {
    const current = items.find(item => item.key === key);
    if (!current) return;
    updateItem(key, {
      draftContent: value,
      dirty: value !== current.content,
      justSaved: false,
    });
  };

  const handleSave = async (key?: EditableAsset['key']) => {
    const targetItems = items.filter(item => item.dirty && (!key || item.key === key));
    if (targetItems.length === 0) return;

    try {
      setError('');
      setSaveMessage('');
      setSaving(!key);
      setSavingKey(key || null);
      const response = await api.updateFeedbackAgentPromptAssets(
        targetItems.map(item => ({
          key: item.key,
          content: item.draftContent,
        })),
      );
      setItems(response.items.map(item => ({
        ...toEditableAsset(item),
        justSaved: !key || item.key === key,
      })));
      setSaveMessage(key
        ? `"${items.find(item => item.key === key)?.title || key}" 已保存，后面的误报反馈会直接用新内容。`
        : '误报反馈 Agent 文件已保存，后面的误报反馈会直接用新内容。');
    } catch (value) {
      setError(getErrorMessage(value, '保存误报反馈 Agent 文件失败。'));
    } finally {
      setSaving(false);
      setSavingKey(null);
    }
  };

  const activeItem = activeKey ? items.find(item => item.key === activeKey) ?? null : null;

  return (
    <Card className="rounded-none border border-border shadow-none">
      <CardHeader className="gap-3 border-b border-border/80 pb-5">
        <div className="flex items-start justify-between gap-6">
          <div className="space-y-3">
            <CardTitle className="text-[24px] font-semibold text-foreground">误报反馈 Agent</CardTitle>
            <CardDescription className="max-w-[980px] text-[14px] leading-7 text-muted-foreground">
              这里单独管理误报反馈 Agent 的三份核心文件：PROMPT.md、AGENT.md、SOUL.md。你改完保存，后面新发起的误报反馈线程会直接用这版。
            </CardDescription>
            <div className="border-l-2 border-primary pl-3 text-[13px] leading-6 text-foreground">
              这部分不走通用审图 stage 配置，而是直接对应误报反馈 Agent 运行时实际读取的 md 文件。
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
            正在读取误报反馈 Agent 文件...
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
      </CardContent>

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
    </Card>
  );
}
