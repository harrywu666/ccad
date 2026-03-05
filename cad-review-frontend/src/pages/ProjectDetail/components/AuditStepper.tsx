// src/pages/ProjectDetail/components/AuditStepper.tsx
import { FileText, FolderKanban, LayoutDashboard, Check } from 'lucide-react';
import type { Project } from '@/types';

export const steps = [
    { id: 'catalog', name: '目录确认', description: '上传并确认图纸总目录', icon: FileText },
    { id: 'drawing-management', name: '图纸管理', description: '图纸/DWG 上传与匹配校对', icon: FolderKanban },
    { id: 'audit', name: '审核报告', description: '智能审阅错漏并生成报告', icon: LayoutDashboard },
];

interface AuditStepperProps {
    currentStep: number;
    project: Project | null;
    onStepClick: (index: number) => void;
}

export default function AuditStepper({ currentStep, project, onStepClick }: AuditStepperProps) {
    const isStepComplete = (index: number) => {
        if (!project) return false;
        if (index === 0) return project.status !== 'new';
        if (index === 1) return project.status === 'ready' || project.status === 'auditing' || project.status === 'done';
        if (index === 2) return project.status === 'done';
        return false;
    };

    const isStepActive = (index: number) => {
        if (!project) return false;
        return currentStep === index;
    };

    return (
        <div className="w-full">
            <div className="flex items-stretch justify-between divide-x divide-border border-y border-border bg-[#FBFBFB]">
                {steps.map((step, index) => {
                    const active = isStepActive(index);
                    const complete = isStepComplete(index);
                    const future = index > currentStep;

                    return (
                        <button
                            key={step.id}
                            onClick={() => onStepClick(index)}
                            className={`flex flex-1 flex-col items-start px-6 py-5 transition-all hover:bg-white relative overflow-hidden group ${active ? 'bg-white' : ''}`}
                        >
                            {/* Active Indicator Bar */}
                            {active && (
                                <div className="absolute top-0 left-0 right-0 h-1 bg-primary" />
                            )}

                            {/* Step Number at top-right */}
                            <div className="absolute top-4 right-6 flex items-center gap-1.5">
                                {complete && !active && <Check className="h-4 w-4 text-success" />}
                                <span className={`text-[14px] font-mono font-medium tracking-tighter ${active ? 'text-primary' : complete ? 'text-success' : 'text-muted-foreground/40'}`}>
                                    0{index + 1}
                                </span>
                            </div>

                            <div className="flex items-center gap-2 mb-1">
                                <span className={`text-[18px] font-bold tracking-tight font-sans ${active ? 'text-foreground' : complete ? 'text-success' : future ? 'text-muted-foreground' : 'text-foreground'}`}>
                                    {step.name}
                                </span>
                            </div>

                            <p className={`text-[13px] mt-0.5 text-left line-clamp-1 ${active ? 'text-muted-foreground' : 'text-muted-foreground/60'}`}>
                                {step.description}
                            </p>
                        </button>
                    );
                })}
            </div>
        </div>
    );
}
