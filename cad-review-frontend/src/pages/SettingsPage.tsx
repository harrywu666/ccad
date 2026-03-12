import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import AppLayout from '@/components/layout/AppLayout';
import SettingsPrompts from './settings/SettingsPrompts';
import SettingsDataTuning from './settings/SettingsDataTuning';
import SettingsSkillPack from './settings/SettingsSkillPack';
import SettingsRuntimeSummary from './settings/SettingsRuntimeSummary';

type SettingsTab = 'agents' | 'skills' | 'tuning' | 'runtime';

const TABS: { key: SettingsTab; label: string }[] = [
  { key: 'agents', label: 'Agent设置' },
  { key: 'skills', label: '审查技能包' },
  { key: 'tuning', label: '误报调优' },
  { key: 'runtime', label: '运行总结' },
];

function isValidTab(value: string | null): value is SettingsTab {
  return value === 'agents' || value === 'skills' || value === 'tuning' || value === 'runtime';
}

function normalizeTab(value: string | null): SettingsTab {
  if (value === 'prompts') return 'agents';
  return isValidTab(value) ? value : 'agents';
}

export default function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const paramTab = searchParams.get('tab');
  const [activeTab, setActiveTab] = useState<SettingsTab>(normalizeTab(paramTab));

  useEffect(() => {
    setActiveTab(normalizeTab(paramTab));
  }, [paramTab]);

  const switchTab = (tab: SettingsTab) => {
    setActiveTab(tab);
    setSearchParams({ tab }, { replace: true });
  };

  return (
    <AppLayout showCategories={false}>
      <section className="space-y-3">
        <h2 className="text-[30px] font-semibold tracking-tight text-foreground">设置</h2>
      </section>

      <nav className="flex gap-0 border-b border-border">
        {TABS.map(tab => (
          <button
            key={tab.key}
            type="button"
            onClick={() => switchTab(tab.key)}
            className={`px-5 py-2.5 text-[14px] font-medium transition-colors ${
              activeTab === tab.key
                ? 'border-b-2 border-primary text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <div className="flex flex-col gap-6">
        {activeTab === 'agents' ? <SettingsPrompts /> : null}
        {activeTab === 'skills' ? <SettingsSkillPack /> : null}
        {activeTab === 'tuning' ? <SettingsDataTuning /> : null}
        {activeTab === 'runtime' ? <SettingsRuntimeSummary /> : null}
      </div>
    </AppLayout>
  );
}
