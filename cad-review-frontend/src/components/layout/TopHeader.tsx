import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import type { Category } from '@/types';
import type { ReactNode } from 'react';

interface TopHeaderProps {
    onBack: () => void;
    title: string;
    category?: Category;
    statusInfo: { label: string; variant: 'default' | 'secondary' | 'success' | 'warning' | 'destructive' };
    isAuditing?: boolean;
    auditPill?: ReactNode;
}

export default function TopHeader({ onBack, title, category, statusInfo, isAuditing = false, auditPill }: TopHeaderProps) {
    return (
        <header className="bg-white border-b border-border sticky top-0 z-50">
            <div className="px-8 py-[18px] flex items-center justify-between w-full">
                <div className="flex items-center gap-3 min-w-0">
                    <h1 className="text-[20px] font-semibold font-sans truncate tracking-tight text-foreground">
                        {title}
                    </h1>
                    {auditPill}
                </div>

                <div className="flex items-center gap-4">
                    {category && (
                        <Badge variant="outline" className="bg-white/40 dark:bg-black/20 border-transparent shadow-none hidden sm:inline-flex rounded-none h-6 px-2" style={{ color: category.color }}>
                            <span className="w-1.5 h-1.5 rounded-none mr-1.5" style={{ backgroundColor: category.color }} />
                            {category.name}
                        </Badge>
                    )}
                    <Button
                        onClick={onBack}
                        className="bg-primary hover:bg-primary/90 rounded-none text-[14px] font-medium text-primary-foreground h-9 px-6 transition-colors"
                    >
                        返回
                    </Button>
                </div>
            </div>
        </header>
    );
}
