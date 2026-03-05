// src/pages/ProjectDetail/components/StepProgressBox.tsx
import { CheckCircle } from 'lucide-react';
import type { Project, AuditStatus } from '@/types';

interface StepProgressBoxProps {
    project: Project | null;
    auditStatus: AuditStatus | null;
}

export default function StepProgressBox({ project, auditStatus }: StepProgressBoxProps) {
    const getStatusText = (stepIndex: number) => {
        if (!project) return { text: '未开始', color: 'text-muted-foreground' };

        // Logic matching the ui.pen steps layout states
        if (project.status === 'new') {
            return stepIndex === 1 ? { text: '进行中', color: 'text-primary' } : { text: '未开始', color: 'text-muted-foreground' };
        }
        if (project.status === 'catalog_locked') {
            if (stepIndex === 1) return { text: '已完成', color: 'text-success' };
            if (stepIndex === 2) return { text: '进行中', color: 'text-primary' };
            return { text: '未开始', color: 'text-muted-foreground' };
        }
        if (project.status === 'matching') {
            if (stepIndex <= 2) return { text: '已完成', color: 'text-success' };
            if (stepIndex === 3) return { text: '进行中', color: 'text-primary' };
            return { text: '未开始', color: 'text-muted-foreground' };
        }
        if (project.status === 'ready') {
            if (stepIndex <= 3) return { text: '已完成', color: 'text-success' };
            if (stepIndex === 4) return { text: '进行中', color: 'text-primary' };
            return { text: '未开始', color: 'text-muted-foreground' };
        }
        if (project.status === 'auditing') {
            if (stepIndex <= 4) return { text: '已完成', color: 'text-success' };
            if (stepIndex === 5) return { text: '进行中', color: 'text-primary' };
        }
        if (project.status === 'done') {
            return { text: '已完成', color: 'text-success' };
        }
        return { text: '未开始', color: 'text-muted-foreground' };
    };

    const stepsList = [
        { title: '① 目录', index: 1 },
        { title: '② 图纸', index: 2 },
        { title: '③ DWG', index: 3 },
        { title: '④ 三线匹配', index: 4 },
        { title: '⑤ 审核报告', index: 5 },
    ];

    return (
        <div className="flex gap-[14px] w-full mb-6 overflow-x-auto pb-2">
            {stepsList.map(step => {
                const status = getStatusText(step.index);
                const isActive = status.text === '进行中';

                return (
                    <div
                        key={step.index}
                        className={`flex-1 min-w-[160px] p-[14px] rounded-none border ${isActive ? 'bg-primary/5 border-primary/20' : 'bg-secondary border-border'} flex flex-col gap-1`}
                    >
                        <span className="text-[13px] font-semibold text-foreground font-sans">{step.title}</span>
                        <span className={`text-[12px] font-sans ${status.color}`}>
                            {status.text}
                        </span>
                    </div>
                );
            })}
        </div>
    );
}
