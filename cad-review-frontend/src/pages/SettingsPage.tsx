import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import AppLayout from '@/components/layout/AppLayout';
import SettingsPrompts from './settings/SettingsPrompts';
import SettingsDataTuning from './settings/SettingsDataTuning';
import SettingsSkillPack from './settings/SettingsSkillPack';

type SettingsTab = 'prompts' | 'skills' | 'tuning';

const TABS: { key: SettingsTab; label: string }[] = [
  { key: 'prompts', label: '提示词设置' },
  { key: 'skills', label: '审查技能包' },
  { key: 'tuning', label: '误报调优' },
];

function isValidTab(value: string | null): value is SettingsTab {
  return value === 'prompts' || value === 'skills' || value === 'tuning';
}

export default function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const paramTab = searchParams.get('tab');
  const [activeTab, setActiveTab] = useState<SettingsTab>(
    isValidTab(paramTab) ? paramTab : 'prompts',
  );

  useEffect(() => {
    if (isValidTab(paramTab)) {
      setActiveTab(paramTab);
    }
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
        {activeTab === 'prompts' ? <SettingsPrompts /> : null}
        {activeTab === 'skills' ? <SettingsSkillPack /> : null}
        {activeTab === 'tuning' ? <SettingsDataTuning /> : null}
      </div>
    </AppLayout>
  );
}
