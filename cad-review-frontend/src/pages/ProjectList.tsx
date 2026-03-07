import { useState, useEffect } from 'react';
import axios from 'axios';
import * as api from '@/api';
import type { Category, Project } from '@/types';
import AppLayout from '@/components/layout/AppLayout';
import ProjectTable from './ProjectList/components/ProjectTable';
import CreateProjectDialog from './ProjectList/components/CreateProjectDialog';
import EditProjectDialog from './ProjectList/components/EditProjectDialog';
import DeleteProjectDialog from './ProjectList/components/DeleteProjectDialog';
import CategoryManagementDialog from './ProjectList/components/CategoryManagementDialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

const statusMap: Record<string, { label: string; variant: 'default' | 'secondary' | 'success' | 'warning' | 'destructive' }> = {
  new: { label: '待开始', variant: 'secondary' },
  catalog_locked: { label: '目录已确认', variant: 'warning' },
  matching: { label: '匹配中', variant: 'warning' },
  ready: { label: '待审核', variant: 'warning' },
  auditing: { label: '审核中', variant: 'warning' },
  done: { label: '已完成', variant: 'success' },
};

export default function ProjectList() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedCategoryId, setSelectedCategoryId] = useState<string>('all');
  const [selectedStatus, setSelectedStatus] = useState<string>('all');
  const [searchKeyword, setSearchKeyword] = useState('');
  const [categoryCount, setCategoryCount] = useState<Record<string, number>>({});
  const [loadError, setLoadError] = useState('');
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [projectToEdit, setProjectToEdit] = useState<Project | null>(null);
  const [isCategoryDialogOpen, setIsCategoryDialogOpen] = useState(false);
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadData();
    }, 6000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const getErrorMessage = (error: unknown, fallback: string) => {
    if (axios.isAxiosError(error)) {
      if (typeof error.response?.data?.detail === 'string') return error.response.data.detail;
      if (error.code === 'ERR_NETWORK') return '无法连接后端服务，请确认后端已启动。';
      return error.message || fallback;
    }
    if (error instanceof Error && error.message) return error.message;
    return fallback;
  };

  const loadData = async () => {
    try {
      setLoadError('');
      const [cats, projs] = await Promise.all([
        api.getCategories(),
        api.getProjects(),
      ]);
      setCategories(cats);
      setProjects(projs);

      const counts: Record<string, number> = { all: projs.length };
      cats.forEach(c => {
        counts[c.id] = projs.filter(p => p.category === c.id).length;
      });
      setCategoryCount(counts);
    } catch (error) {
      setLoadError(getErrorMessage(error, '加载数据失败，请稍后重试。'));
      console.error('加载数据失败:', error);
    }
  };

  const handleDeleteProject = (project: Project) => {
    setProjectToDelete(project);
  };

  const handleEditProject = (project: Project) => {
    setProjectToEdit(project);
  };

  const confirmDeleteProject = async () => {
    if (!projectToDelete) return;
    try {
      setIsDeleting(true);
      await api.deleteProject(projectToDelete.id);
      setProjectToDelete(null);
      await loadData();
    } catch (error) {
      console.error('删除项目失败:', error);
    } finally {
      setIsDeleting(false);
    }
  };

  const keyword = searchKeyword.trim().toLowerCase();
  const filteredProjects = projects.filter((project) => {
    const categoryMatched = selectedCategoryId === 'all' || project.category === selectedCategoryId;
    const statusMatched = selectedStatus === 'all' || project.status === selectedStatus;
    const nameMatched = !keyword || project.name.toLowerCase().includes(keyword);
    return categoryMatched && statusMatched && nameMatched;
  });

  return (
    <AppLayout
      categories={categories}
      categoryCount={categoryCount}
      activeCategoryId={selectedCategoryId}
      onCategorySelect={setSelectedCategoryId}
      onManageCategories={() => setIsCategoryDialogOpen(true)}
    >
      {/* Header Sec */}
      <section className="flex items-center justify-between w-full">
        <h2 className="text-[28px] font-semibold font-sans tracking-tight text-foreground">
          项目列表
        </h2>
        <button
          onClick={() => setIsCreateOpen(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 transition-colors rounded-none"
        >
          <span className="text-[13px] font-medium font-sans text-primary-foreground">新建项目</span>
        </button>
      </section>

      {/* Filter / Search Sec - As per design, it's a simple display for now. Adding if needed for later functionality */}
      <section className="flex gap-4 w-full mt-6">
        <div className="flex-1 bg-secondary px-4 py-3 rounded-none flex items-center">
          <input
            type="text"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            placeholder="搜索项目名称..."
            className="w-full bg-transparent border-0 p-0 text-[13px] font-sans text-foreground placeholder:text-muted-foreground outline-none"
          />
        </div>
        <div className="bg-secondary px-4 py-3 rounded-none min-w-[200px] flex items-center gap-2">
          <span className="text-[13px] text-foreground font-sans shrink-0">状态：</span>
          <Select value={selectedStatus} onValueChange={setSelectedStatus}>
            <SelectTrigger className="h-auto border-0 bg-transparent p-0 shadow-none focus:ring-0 focus:ring-offset-0 text-[13px] font-sans text-foreground">
              <SelectValue placeholder="全部" />
            </SelectTrigger>
            <SelectContent className="bg-white border-border rounded-none shadow-sm">
              <SelectItem value="all" className="text-[13px] rounded-none cursor-pointer">全部</SelectItem>
              {Object.entries(statusMap).map(([value, info]) => (
                <SelectItem key={value} value={value} className="text-[13px] rounded-none cursor-pointer">
                  {info.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </section>

      <ProjectTable
        projects={filteredProjects}
        categories={categories}
        loadError={loadError}
        statusMap={statusMap}
        onDelete={handleDeleteProject}
        onEdit={handleEditProject}
        onCreateClick={() => setIsCreateOpen(true)}
      />

      <CreateProjectDialog
        isOpen={isCreateOpen}
        onOpenChange={setIsCreateOpen}
        categories={categories}
        onSuccess={loadData}
      />

      <EditProjectDialog
        isOpen={Boolean(projectToEdit)}
        onOpenChange={(open) => !open && setProjectToEdit(null)}
        project={projectToEdit}
        categories={categories}
        onSuccess={loadData}
      />

      <DeleteProjectDialog
        open={Boolean(projectToDelete)}
        projectName={projectToDelete?.name || ''}
        deleting={isDeleting}
        onOpenChange={(open) => !open && setProjectToDelete(null)}
        onConfirm={confirmDeleteProject}
      />

      <CategoryManagementDialog
        isOpen={isCategoryDialogOpen}
        onOpenChange={setIsCategoryDialogOpen}
        categories={categories}
        activeCategoryId={selectedCategoryId}
        onActiveCategoryInvalidated={() => setSelectedCategoryId('all')}
        onSuccess={loadData}
      />
    </AppLayout>
  );
}
