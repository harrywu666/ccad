import { Link } from 'react-router-dom';
import { Edit3, MoreVertical, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import type { Project, Category } from '@/types';

interface ProjectTableProps {
    projects: Project[];
    categories: Category[];
    loadError: string;
    statusMap: Record<string, { label: string; variant: 'default' | 'secondary' | 'success' | 'warning' | 'destructive' }>;
    onDelete: (project: Project) => void;
    onEdit: (project: Project) => void;
    onCreateClick: () => void;
}

export default function ProjectTable({ projects, categories, loadError, statusMap, onDelete, onEdit, onCreateClick }: ProjectTableProps) {
    const getCategoryName = (project: Project) => categories.find(c => c.id === project.category)?.name || '未知';

    const getStatusStyle = (project: Project) => {
        const status = statusMap[project.status] || { label: project.status, variant: 'secondary' };
        let statusColor = 'var(--color-muted-foreground)';
        let statusBg = 'var(--color-secondary)';

        if (['auditing', 'matching', 'ready'].includes(project.status)) {
            statusColor = 'var(--color-primary)';
            statusBg = 'var(--color-secondary)';
        }
        if (project.status === 'done') {
            statusColor = 'var(--color-success)';
            statusBg = '#F0FDF4';
        }

        return { label: status.label, statusColor, statusBg };
    };

    const formatDate = (dateStr: string) => {
        const date = new Date(dateStr);
        return date.toLocaleDateString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit'
        });
    };

    const renderProjectCells = (project: Project | undefined, isLeftGroup: boolean) => {
        const rightBorderClass = isLeftGroup ? 'border-r border-border' : '';
        if (!project) {
            return (
                <>
                    <td className="px-5 py-5 text-[14px] text-muted-foreground w-full max-w-0">-</td>
                    <td className="px-2 py-5 text-[14px] text-muted-foreground text-center whitespace-nowrap">-</td>
                    <td className="px-2 py-5 text-[14px] text-muted-foreground text-center whitespace-nowrap">-</td>
                    <td className="px-2 py-5 text-[14px] text-muted-foreground text-center whitespace-nowrap">-</td>
                    <td className={`px-2 py-5 text-[14px] text-muted-foreground text-center whitespace-nowrap ${rightBorderClass}`}>-</td>
                </>
            );
        }

        const status = getStatusStyle(project);

        return (
            <>
                <td className="px-5 py-5 w-full max-w-0">
                    <div className="flex items-center min-w-0 w-full">
                        <Link
                            to={`/projects/${project.id}`}
                            className="min-w-0 truncate text-[16px] font-semibold text-foreground hover:text-primary transition-colors block"
                            title={project.name}
                        >
                            {project.name}
                        </Link>
                    </div>
                </td>
                <td className="px-2 py-5 text-center whitespace-nowrap">
                    <div
                        className="inline-flex min-w-[56px] items-center justify-center whitespace-nowrap px-2 py-1 border border-border/50"
                        style={{ backgroundColor: status.statusBg }}
                    >
                        <span className="text-[12px] leading-none font-semibold whitespace-nowrap" style={{ color: status.statusColor }}>
                            {status.label}
                        </span>
                    </div>
                </td>
                <td className="px-2 py-5 text-[14px] text-foreground text-center whitespace-nowrap">
                    {getCategoryName(project)}
                </td>
                <td className="px-2 py-5 text-[14px] text-foreground text-center whitespace-nowrap">
                    {formatDate(project.created_at)}
                </td>
                <td className={`px-2 py-5 text-center whitespace-nowrap ${rightBorderClass}`}>
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 rounded-none border-0 bg-transparent p-0 shadow-none hover:bg-secondary data-[state=open]:bg-secondary focus-visible:ring-0"
                                title="操作"
                            >
                                <MoreVertical className="w-4 h-4 text-muted-foreground" />
                            </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-36 rounded-none">
                            <DropdownMenuItem onClick={() => onEdit(project)}>
                                <Edit3 className="w-4 h-4" />
                                编辑
                            </DropdownMenuItem>
                            <DropdownMenuItem variant="destructive" onClick={() => onDelete(project)}>
                                <Trash2 className="w-4 h-4" />
                                删除
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </td>
            </>
        );
    };

    return (
        <section className="w-full mt-6">
            {loadError && (
                <div className="p-4 text-[14px] text-primary border border-border bg-white mb-4">
                    {loadError}
                </div>
            )}

            {projects.length === 0 && !loadError ? (
                <div className="p-16 flex flex-col items-center justify-center text-center bg-white border border-border">
                    <span className="text-[14px] text-muted-foreground mb-4">暂无项目</span>
                    <button
                        onClick={onCreateClick}
                        className="px-6 py-2.5 bg-primary text-primary-foreground text-[14px] font-sans font-medium rounded-none hover:bg-primary/90 transition-colors"
                    >
                        创建第一个项目
                    </button>
                </div>
            ) : (
                <>
                    <div className="hidden xl:block border border-border bg-white overflow-x-auto overflow-y-hidden relative">
                        <div className="pointer-events-none absolute inset-y-0 left-1/2 w-px bg-border z-[1]" />
                        <table className="w-full min-w-[1000px] table-fixed text-left">
                            <thead className="bg-zinc-100 border-b border-border">
                                <tr>
                                    <th className="w-full px-5 py-4 text-[13px] font-semibold text-muted-foreground whitespace-nowrap">项目名称</th>
                                    <th className="w-[80px] px-2 py-4 text-[13px] font-semibold text-muted-foreground text-center whitespace-nowrap">状态</th>
                                    <th className="w-[80px] px-2 py-4 text-[13px] font-semibold text-muted-foreground text-center whitespace-nowrap">类型</th>
                                    <th className="w-[108px] px-2 py-4 text-[13px] font-semibold text-muted-foreground text-center whitespace-nowrap">创建时间</th>
                                    <th className="w-[64px] px-2 py-4 text-[13px] font-semibold text-muted-foreground border-r border-border text-center whitespace-nowrap">编辑</th>
                                    <th className="w-full px-5 py-4 text-[13px] font-semibold text-muted-foreground whitespace-nowrap">项目名称</th>
                                    <th className="w-[80px] px-2 py-4 text-[13px] font-semibold text-muted-foreground text-center whitespace-nowrap">状态</th>
                                    <th className="w-[80px] px-2 py-4 text-[13px] font-semibold text-muted-foreground text-center whitespace-nowrap">类型</th>
                                    <th className="w-[108px] px-2 py-4 text-[13px] font-semibold text-muted-foreground text-center whitespace-nowrap">创建时间</th>
                                    <th className="w-[64px] px-2 py-4 text-[13px] font-semibold text-muted-foreground text-center whitespace-nowrap">编辑</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {Array.from({ length: Math.ceil(projects.length / 2) }).map((_, rowIndex) => {
                                    const leftProject = projects[rowIndex];
                                    const rightProject = projects[rowIndex + Math.ceil(projects.length / 2)];
                                    return (
                                        <tr key={`project-row-${rowIndex}`} className="hover:bg-secondary/20 transition-colors">
                                            {renderProjectCells(leftProject, true)}
                                            {renderProjectCells(rightProject, false)}
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>

                    <div className="xl:hidden border border-border bg-white overflow-x-auto overflow-y-hidden">
                        <table className="w-full min-w-[500px] table-fixed text-left">
                            <thead className="bg-zinc-100 border-b border-border">
                                <tr>
                                    <th className="w-full px-5 py-4 text-[13px] font-semibold text-muted-foreground whitespace-nowrap">项目名称</th>
                                    <th className="w-[84px] px-2 py-4 text-[13px] font-semibold text-muted-foreground text-center whitespace-nowrap">状态</th>
                                    <th className="w-[84px] px-2 py-4 text-[13px] font-semibold text-muted-foreground text-center whitespace-nowrap">类型</th>
                                    <th className="w-[112px] px-2 py-4 text-[13px] font-semibold text-muted-foreground text-center whitespace-nowrap">创建时间</th>
                                    <th className="w-[64px] px-2 py-4 text-[13px] font-semibold text-muted-foreground text-center whitespace-nowrap">编辑</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {projects.map((project) => (
                                    <tr key={`project-mobile-${project.id}`} className="hover:bg-secondary/20 transition-colors">
                                        {renderProjectCells(project, false)}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </>
            )}
        </section>
    );
}
