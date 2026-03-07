import { ReactNode } from 'react';
import Sidebar from './Sidebar';
import type { Category } from '@/types';

interface AppLayoutProps {
    children: ReactNode;
    categories?: Category[];
    categoryCount?: Record<string, number>;
    activeCategoryId?: string;
    onCategorySelect?: (id: string) => void;
    onManageCategories?: () => void;
    showCategories?: boolean;
    showSidebar?: boolean;
    fullWidth?: boolean;
}

export default function AppLayout({
    children,
    categories,
    categoryCount,
    activeCategoryId,
    onCategorySelect,
    onManageCategories,
    showCategories,
    showSidebar = true,
    fullWidth = false,
}: AppLayoutProps) {
    const contentClassName = fullWidth
        ? 'w-full max-w-none'
        : (showSidebar ? 'max-w-[1440px]' : 'max-w-7xl mx-auto w-full');

    return (
        <div className="min-h-screen bg-background flex font-sans text-foreground">
            {showSidebar && (
                <Sidebar
                    categories={categories}
                    categoryCount={categoryCount}
                    activeCategoryId={activeCategoryId}
                    onCategorySelect={onCategorySelect}
                    onManageCategories={onManageCategories}
                    showCategories={showCategories}
                />
            )}
            <main className="flex-1 min-w-0 flex flex-col gap-8 relative py-8 px-8 w-full">
                <div className={contentClassName}>
                    {children}
                </div>
            </main>
        </div>
    );
}
