import { ReactNode } from 'react';
import Sidebar from './Sidebar';
import type { Category } from '@/types';

interface AppLayoutProps {
    children: ReactNode;
    categories?: Category[];
    categoryCount?: Record<string, number>;
    activeCategoryId?: string;
    onCategorySelect?: (id: string) => void;
    showCategories?: boolean;
    showSidebar?: boolean;
}

export default function AppLayout({
    children,
    categories,
    categoryCount,
    activeCategoryId,
    onCategorySelect,
    showCategories,
    showSidebar = true
}: AppLayoutProps) {
    return (
        <div className="min-h-screen bg-background flex font-sans text-foreground">
            {showSidebar && (
                <Sidebar
                    categories={categories}
                    categoryCount={categoryCount}
                    activeCategoryId={activeCategoryId}
                    onCategorySelect={onCategorySelect}
                    showCategories={showCategories}
                />
            )}
            <main className={`flex-1 flex flex-col gap-8 relative overflow-hidden py-8 px-8 ${showSidebar ? 'max-w-[1440px]' : 'max-w-7xl mx-auto w-full'}`}>
                {children}
            </main>
        </div>
    );
}
