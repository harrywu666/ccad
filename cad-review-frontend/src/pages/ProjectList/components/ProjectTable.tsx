import { Link } from 'react-router-dom';
import { Trash2 } from 'lucide-react';
import type { Project, Category } from '@/types';

interface ProjectTableProps {
    projects: Project[];
    categories: Category[];
    loadError: string;
    statusMap: Record<string, { label: string; variant: 'default' | 'secondary' | 'success' | 'warning' | 'destructive' }>;
    onDelete: (project: Project, e: React.MouseEvent) => void;
    onCreateClick: () => void;
}

export default function ProjectTable({ projects, categories, loadError, statusMap, onDelete, onCreateClick }: ProjectTableProps) {
    const formatDate = (dateStr: string) => {
        const date = new Date(dateStr);
        return date.toLocaleDateString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit'
        });
    };

    return (
        <section className="w-full flex flex-col border border-border mt-6">
            {/* Table Header */}
            <div className="flex items-center px-5 py-3 bg-secondary border-b border-border">
                <div className="w-[360px] text-[13px] font-medium text-muted-foreground">项目名称</div>
                <div className="w-[120px] text-[13px] font-medium text-muted-foreground">状态</div>
                <div className="w-[90px] text-[13px] font-medium text-muted-foreground">类型</div>
                <div className="w-[130px] text-[13px] font-medium text-muted-foreground">添加时间</div>
                <div className="w-[60px] text-[13px] font-medium text-muted-foreground text-right">操作</div>
            </div>

            {loadError && (
                <div className="p-4 text-[14px] text-primary border-b border-border">
                    {loadError}
                </div>
            )}

            {/* Table Body */}
            {projects.length === 0 && !loadError ? (
                <div className="p-16 flex flex-col items-center justify-center text-center bg-white">
                    <span className="text-[14px] text-muted-foreground mb-4">暂无项目</span>
                    <button
                        onClick={onCreateClick}
                        className="px-6 py-2.5 bg-primary text-primary-foreground text-[14px] font-sans font-medium rounded-none hover:bg-primary/90 transition-colors"
                    >
                        创建第一个项目
                    </button>
                </div>
            ) : (
                <div className="flex flex-col">
                    {projects.map((project, index) => {
                        const category = categories.find(c => c.id === project.category);
                        const status = statusMap[project.status] || { label: project.status, variant: 'secondary' };

                        let statusColor = 'var(--color-muted-foreground)';
                        let statusBg = 'var(--color-secondary)';

                        if (['auditing', 'matching', 'ready'].includes(project.status)) {
                            statusColor = 'var(--color-primary)';
                            statusBg = 'var(--color-secondary)';
                        }
                        if (project.status === 'done') {
                            statusColor = 'var(--color-success)';
                            statusBg = '#F0FDF4'; // light green
                        }

                        return (
                            <Link
                                key={project.id}
                                to={`/projects/${project.id}`}
                                className={`flex items-center px-5 py-4 bg-white border-b border-border last:border-b-0 hover:bg-secondary/40 transition-colors group`}
                            >
                                <div className="w-[360px] text-[14px] font-medium font-sans text-foreground truncate pr-6">
                                    {project.name}
                                </div>
                                <div className="w-[120px]">
                                    <div
                                        className="inline-flex px-2.5 py-1 rounded-none border border-border/50"
                                        style={{ backgroundColor: statusBg }}
                                    >
                                        <span className="text-[12px] font-medium" style={{ color: statusColor }}>{status.label}</span>
                                    </div>
                                </div>
                                <div className="w-[90px] text-[14px] font-sans text-muted-foreground">
                                    {category?.name || '未知'}
                                </div>
                                <div className="w-[130px] text-[14px] font-sans text-muted-foreground">
                                    {formatDate(project.updated_at)}
                                </div>
                                <div className="w-[60px] text-right">
                                    <button
                                        onClick={(e) => onDelete(project, e)}
                                        className="text-muted-foreground hover:text-primary transition-colors opacity-0 group-hover:opacity-100 p-1"
                                        title="删除项目"
                                    >
                                        <Trash2 className="w-4 h-4 inline-block" />
                                    </button>
                                </div>
                            </Link>
                        );
                    })}
                </div>
            )}
        </section>
    );
}
