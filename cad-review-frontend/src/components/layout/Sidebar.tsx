import { Link, useLocation } from 'react-router-dom';
import { Settings } from 'lucide-react';
import type { Category } from '@/types';

interface SidebarProps {
    categories?: Category[];
    categoryCount?: Record<string, number>;
    activeCategoryId?: string | 'all';
    onCategorySelect?: (id: string) => void;
    onManageCategories?: () => void;
    showCategories?: boolean;
}

export default function Sidebar({
    categories = [],
    categoryCount = {},
    activeCategoryId = 'all',
    onCategorySelect,
    onManageCategories,
    showCategories = true
}: SidebarProps) {
    const location = useLocation();

    const isListActive = location.pathname === '/';

    // NOTE: For now, clicking System Settings doesn't navigate anywhere per requirements, 
    // but it's styled properly.
    const isSettingsActive = location.pathname.startsWith('/settings');

    const handleCategoryClick = (id: string) => {
        if (onCategorySelect) {
            onCategorySelect(id);
        }
    };

    return (
        <aside className="w-[304px] shrink-0 border-r border-border flex flex-col pt-11 pb-11 bg-white h-screen sticky top-0">
            {/* Logo Row */}
            <div className="flex items-center gap-3 px-8 mb-12">
                <div className="w-5 h-5 bg-primary rounded-none" />
                <h1 className="text-[22px] font-semibold font-heading text-foreground">
                    施工图AI审核系统
                </h1>
            </div>

            {/* Nav List */}
            <nav className="flex flex-col w-full">
                <Link
                    to="/"
                    onClick={() => handleCategoryClick('all')}
                    className={`flex items-center gap-3 px-8 py-3 w-full cursor-pointer transition-colors group ${isListActive && activeCategoryId === 'all' ? '' : 'hover:bg-secondary/50'}`}
                >
                    <div className="w-2 h-2 bg-primary" />
                    <span className="text-[18px] font-sans font-bold text-primary">项目列表</span>
                </Link>
            </nav>

            {/* Project Categories */}
            {showCategories && (
                <div className="mt-6 px-8 flex flex-col gap-6 flex-1 overflow-y-auto pl-[52px]">
                    <div
                        onClick={() => handleCategoryClick('all')}
                        className={`flex items-center gap-3 text-[16px] cursor-pointer hover:opacity-80 transition-opacity ${activeCategoryId === 'all' ? 'font-bold text-foreground' : 'font-medium text-muted-foreground'}`}
                    >
                        <span>全部</span>
                        <span>{categoryCount['all'] || 0}</span>
                    </div>

                    <div className="flex flex-col gap-6">
                        {categories.map(cat => (
                            <div
                                key={cat.id}
                                onClick={() => handleCategoryClick(cat.id)}
                                className={`flex items-center gap-3 text-[15px] cursor-pointer hover:text-foreground transition-colors ${activeCategoryId === cat.id ? 'font-bold text-foreground' : 'font-medium text-muted-foreground'}`}
                            >
                                <span>{cat.name}</span>
                                <span>{categoryCount[cat.id] || 0}</span>
                            </div>
                        ))}
                    </div>

                    <div className="mt-4">
                        <button
                            onClick={() => onManageCategories?.()}
                            className="bg-foreground text-background text-[14px] font-medium py-2.5 px-6 rounded-none hover:bg-foreground/90 transition-colors"
                        >
                            管理分类
                        </button>
                    </div>
                </div>
            )}

            <div className="mt-auto px-8">
                <Link
                    to="/settings"
                    className={`flex items-center gap-3 px-4 py-2.5 border border-border rounded-none transition-colors ${
                        isSettingsActive ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:bg-secondary/60 hover:text-foreground'
                    }`}
                >
                    <Settings className="h-4 w-4" />
                    <span className="text-[14px] font-medium">设置</span>
                </Link>
            </div>
        </aside>
    );
}
