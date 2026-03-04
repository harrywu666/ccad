import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Plus, Search, Settings, Home, Building2, Building, Trash2, Briefcase, Frame, Loader2 } from 'lucide-react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import * as api from '@/api';
import type { Category, Project } from '@/types';

const statusMap: Record<string, { label: string; variant: 'default' | 'secondary' | 'success' | 'warning' | 'destructive' }> = {
  new: { label: '待开始', variant: 'secondary' },
  catalog_locked: { label: '目录已确认', variant: 'warning' },
  matching: { label: '匹配中', variant: 'warning' },
  ready: { label: '待审核', variant: 'warning' },
  auditing: { label: '审核中', variant: 'warning' },
  done: { label: '已完成', variant: 'success' },
};

const categoryIcons: Record<string, React.ReactNode> = {
  住宅: <Building2 className="h-4 w-4" />,
  商业: <Building className="h-4 w-4" />,
  办公: <Briefcase className="h-4 w-4" />,
  酒店: <Home className="h-4 w-4" />,
  其他: <Settings className="h-4 w-4" />,
};

export default function ProjectList() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isCategoryOpen, setIsCategoryOpen] = useState(false);
  const [newProject, setNewProject] = useState({ name: '', category: '', tags: [] as string[], description: '' });
  const [newTag, setNewTag] = useState('');
  const [categoryCount, setCategoryCount] = useState<Record<string, number>>({});
  const [loadError, setLoadError] = useState('');
  const [createError, setCreateError] = useState('');
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCategory, statusFilter, searchTerm]);

  const getErrorMessage = (error: unknown, fallback: string) => {
    if (axios.isAxiosError(error)) {
      if (typeof error.response?.data?.detail === 'string') {
        return error.response.data.detail;
      }
      if (error.code === 'ERR_NETWORK') {
        return '无法连接后端服务，请确认后端已启动（默认 http://127.0.0.1:7000）。';
      }
      return error.message || fallback;
    }
    if (error instanceof Error && error.message) {
      return error.message;
    }
    return fallback;
  };

  const loadData = async (
    filters?: { category?: string; status?: string; search?: string }
  ) => {
    const category = filters?.category ?? selectedCategory;
    const status = filters?.status ?? statusFilter;
    const search = filters?.search ?? searchTerm;
    try {
      setLoadError('');
      const [cats, projs] = await Promise.all([
        api.getCategories(),
        api.getProjects({
          category: category !== 'all' ? category : undefined,
          status: status !== 'all' ? status : undefined,
          search: search || undefined,
        }),
      ]);
      setCategories(cats);
      setProjects(projs);

      const allProjs = await api.getProjects();
      const counts: Record<string, number> = { all: allProjs.length };
      cats.forEach(c => {
        counts[c.id] = allProjs.filter(p => p.category === c.id).length;
      });
      setCategoryCount(counts);
    } catch (error) {
      setLoadError(getErrorMessage(error, '加载数据失败，请稍后重试。'));
      console.error('加载数据失败:', error);
    }
  };

  const handleCreateProject = async () => {
    if (!newProject.name.trim()) {
      setCreateError('请先填写项目名称。');
      return;
    }
    try {
      setCreateError('');
      setIsCreating(true);
      await api.createProject({
        name: newProject.name,
        category: newProject.category || undefined,
        tags: newProject.tags.length > 0 ? newProject.tags : undefined,
        description: newProject.description || undefined,
      });
      setIsCreateOpen(false);
      setNewProject({ name: '', category: '', tags: [], description: '' });
      setSearchTerm('');
      setSelectedCategory('all');
      setStatusFilter('all');
      await loadData({ category: 'all', status: 'all', search: '' });
    } catch (error) {
      setCreateError(getErrorMessage(error, '创建项目失败，请稍后重试。'));
      console.error('创建项目失败:', error);
    } finally {
      setIsCreating(false);
    }
  };

  const handleDeleteProject = async (id: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm('确定要删除这个项目吗？')) return;
    try {
      await api.deleteProject(id);
      loadData();
    } catch (error) {
      console.error('删除项目失败:', error);
    }
  };

  const addTag = () => {
    if (newTag.trim() && !newProject.tags.includes(newTag.trim())) {
      setNewProject({ ...newProject, tags: [...newProject.tags, newTag.trim()] });
      setNewTag('');
    }
  };

  const removeTag = (tag: string) => {
    setNewProject({ ...newProject, tags: newProject.tags.filter(t => t !== tag) });
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit'
    });
  };

  return (
    <div className="min-h-screen bg-gray-50/50 dark:bg-zinc-950 relative overflow-hidden">
      {/* Ambient Background Lights */}
      <div className="absolute top-0 left-[-10%] w-[40%] h-[40%] bg-primary/10 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[30%] h-[50%] bg-blue-400/10 rounded-full blur-[100px] pointer-events-none" />

      {/* Header */}
      <header className="glass-header">
        <div className="container mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-primary/10 p-2 rounded-xl border border-primary/20">
              <Frame className="h-6 w-6 text-primary" />
            </div>
            <h1 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-gray-900 to-gray-600 dark:from-gray-100 dark:to-gray-400">
              施工图 AI 审核系统
            </h1>
          </div>
          <Button onClick={() => setIsCreateOpen(true)} className="rounded-full shadow-lg shadow-primary/25">
            <Plus className="h-4 w-4 mr-2" />
            新建项目
          </Button>
        </div>
      </header>

      <div className="container mx-auto px-6 py-8 flex gap-8 relative z-10">
        {/* Sidebar */}
        <aside className="w-56 flex-shrink-0">
          <Card className="glass-card border-white/40 dark:border-zinc-800/50">
            <CardHeader className="pb-4">
              <CardTitle className="text-sm font-semibold tracking-wider text-muted-foreground uppercase">项目分类</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1">
              <button
                onClick={() => setSelectedCategory('all')}
                className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm transition-all duration-300 ${selectedCategory === 'all'
                    ? 'bg-primary/10 text-primary font-medium shadow-sm'
                    : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100/50 dark:hover:bg-zinc-800/50'
                  }`}
              >
                <span className="flex items-center gap-3">
                  <Home className="h-4 w-4" />
                  全部项目
                </span>
                <Badge variant={selectedCategory === 'all' ? 'default' : 'secondary'} className="h-5 px-1.5 min-w-[1.25rem]">
                  {categoryCount.all || 0}
                </Badge>
              </button>

              <div className="py-2">
                <div className="h-px bg-gradient-to-r from-transparent via-gray-200 dark:via-zinc-800 to-transparent" />
              </div>

              {categories.map(cat => {
                const isSelected = selectedCategory === cat.id;
                return (
                  <button
                    key={cat.id}
                    onClick={() => setSelectedCategory(cat.id)}
                    className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm transition-all duration-300 ${isSelected
                        ? 'bg-primary/10 text-primary font-medium shadow-sm'
                        : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100/50 dark:hover:bg-zinc-800/50'
                      }`}
                  >
                    <span className="flex items-center gap-3">
                      <span className="flex items-center justify-center w-4 h-4 rounded-full border bg-white dark:bg-zinc-900 shadow-sm">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: cat.color }} />
                      </span>
                      {cat.name}
                    </span>
                    <Badge variant={isSelected ? 'default' : 'secondary'} className="h-5 px-1.5 min-w-[1.25rem]">
                      {categoryCount[cat.id] || 0}
                    </Badge>
                  </button>
                );
              })}
            </CardContent>

            <CardFooter className="pt-2 pb-4">
              <Button
                variant="ghost"
                onClick={() => setIsCategoryOpen(true)}
                className="w-full text-muted-foreground hover:text-foreground h-9"
              >
                <Settings className="h-4 w-4 mr-2" />
                管理分类
              </Button>
            </CardFooter>
          </Card>
        </aside>

        {/* Main Content */}
        <main className="flex-1 min-w-0">
          {/* Filters & Search */}
          <div className="glass-card rounded-2xl p-4 mb-8 flex flex-wrap gap-4 items-center shadow-sm">
            <div className="flex-1 min-w-[200px] relative group">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
              <Input
                className="pl-10 h-10 bg-white/50 dark:bg-black/20 border-gray-200/50 dark:border-zinc-800/50 focus-visible:ring-1 shadow-inner"
                placeholder="搜索项目名称..."
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
              />
            </div>
            <div className="w-px h-8 bg-gray-200 dark:bg-zinc-800 mx-2 hidden sm:block" />
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-[180px] h-10 bg-white/50 dark:bg-black/20 border-gray-200/50 dark:border-zinc-800/50">
                <SelectValue placeholder="全部状态" />
              </SelectTrigger>
              <SelectContent className="glass">
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="new">待开始</SelectItem>
                <SelectItem value="catalog_locked">目录已确认</SelectItem>
                <SelectItem value="matching">匹配中</SelectItem>
                <SelectItem value="ready">待审核</SelectItem>
                <SelectItem value="auditing">审核中</SelectItem>
                <SelectItem value="done">已完成</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {loadError && (
            <div className="mb-6 rounded-xl border border-red-200 bg-red-50/80 px-4 py-3 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
              {loadError}
            </div>
          )}

          {/* Project Grid */}
          {projects.length === 0 ? (
            <div className="glass-card rounded-2xl p-16 flex flex-col items-center justify-center text-center border-dashed border-2 border-gray-300 dark:border-zinc-800">
              <div className="w-20 h-20 bg-primary/5 rounded-full flex items-center justify-center mb-6 shadow-inner">
                <Frame className="h-10 w-10 text-primary/40" />
              </div>
              <h3 className="text-xl font-semibold mb-2">暂无项目</h3>
              <p className="text-muted-foreground max-w-sm mb-8">
                您还没有任何当前分类下的图纸审核项目。创建一个新项目来开启智能审核之旅。
              </p>
              <Button onClick={() => setIsCreateOpen(true)} size="lg" className="rounded-full shadow-lg shadow-primary/20 hover-lift">
                <Plus className="h-5 w-5 mr-2" />
                创建第一个项目
              </Button>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
              {projects.map(project => {
                const category = categories.find(c => c.id === project.category);
                const status = statusMap[project.status] || { label: project.status, variant: 'secondary' };
                const tags: string[] = project.tags ? JSON.parse(project.tags) : [];

                return (
                  <Link key={project.id} to={`/projects/${project.id}`} className="block group">
                    <Card className="glass-card h-full flex flex-col hover-lift border-white/60 dark:border-white/5 overflow-hidden">
                      <CardHeader className="pb-3 px-5 pt-5 relative">
                        {/* Decorative gradient orb */}
                        <div className="absolute top-0 right-0 w-24 h-24 bg-primary/5 rounded-bl-full -z-10 group-hover:bg-primary/10 transition-colors" />

                        <div className="flex items-start justify-between gap-4">
                          <CardTitle className="text-lg leading-tight line-clamp-2 group-hover:text-primary transition-colors">
                            {project.name}
                          </CardTitle>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity -mr-2 -mt-2 hover:bg-red-50 dark:hover:bg-red-950/30 text-gray-400 hover:text-red-500 rounded-full"
                            onClick={e => handleDeleteProject(project.id, e)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                        {project.description && (
                          <p className="text-sm text-muted-foreground line-clamp-1 mt-1.5">
                            {project.description}
                          </p>
                        )}
                      </CardHeader>
                      <CardContent className="px-5 pb-5 flex-1 flex flex-col">
                        <div className="flex flex-wrap gap-1.5 mb-4">
                          {category && (
                            <Badge
                              variant="outline"
                              className="bg-white/50 dark:bg-black/20 border-transparent shadow-sm"
                              style={{ color: category.color }}
                            >
                              <span className="w-1.5 h-1.5 rounded-full mr-1.5" style={{ backgroundColor: category.color }} />
                              {category.name}
                            </Badge>
                          )}
                          {tags.slice(0, 3).map((tag: string) => (
                            <Badge key={tag} variant="secondary" className="bg-gray-100/50 dark:bg-zinc-800/50 font-normal">
                              {tag}
                            </Badge>
                          ))}
                          {tags.length > 3 && (
                            <Badge variant="secondary" className="bg-gray-100/50 dark:bg-zinc-800/50 font-normal">
                              +{tags.length - 3}
                            </Badge>
                          )}
                        </div>
                        <div className="flex items-center justify-between mt-auto pt-4 border-t border-gray-100 dark:border-zinc-800/50">
                          <Badge variant={status.variant} className="shadow-sm">
                            <span className="relative flex h-2 w-2 mr-1.5">
                              {project.status === 'auditing' || project.status === 'matching' ? (
                                <>
                                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"></span>
                                  <span className="relative inline-flex rounded-full h-2 w-2 bg-white"></span>
                                </>
                              ) : (
                                <span className="relative inline-flex rounded-full h-2 w-2 bg-current opacity-70"></span>
                              )}
                            </span>
                            {status.label}
                          </Badge>
                          <span className="text-xs font-medium text-muted-foreground bg-gray-100/50 dark:bg-zinc-900/50 px-2 py-1 rounded-md">
                            {formatDate(project.updated_at)}
                          </span>
                        </div>
                      </CardContent>
                    </Card>
                  </Link>
                );
              })}
            </div>
          )}
        </main>
      </div>

      {/* Create Project Dialog */}
      <Dialog
        open={isCreateOpen}
        onOpenChange={open => {
          setIsCreateOpen(open);
          if (!open) {
            setCreateError('');
            setIsCreating(false);
          }
        }}
      >
        <DialogContent className="glass sm:max-w-md border-white/20">
          <DialogHeader>
            <DialogTitle className="text-xl">新建审核项目</DialogTitle>
            <DialogDescription>
              创建一个全新的图纸审核任务，准备上传您的目录与图纸。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-5 py-4">
            <div className="space-y-2">
              <Label htmlFor="name" className="text-gray-700 dark:text-gray-300">项目名称 <span className="text-red-500">*</span></Label>
              <Input
                id="name"
                placeholder="例如：上海某某旗舰店室内方案..."
                value={newProject.name}
                onChange={e => {
                  setNewProject({ ...newProject, name: e.target.value });
                  if (createError) setCreateError('');
                }}
                className="bg-white/50 dark:bg-black/20"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="category" className="text-gray-700 dark:text-gray-300">项目分类</Label>
                <Select value={newProject.category} onValueChange={v => {
                  setNewProject({ ...newProject, category: v });
                  if (createError) setCreateError('');
                }}>
                  <SelectTrigger className="bg-white/50 dark:bg-black/20">
                    <SelectValue placeholder="选择分类" />
                  </SelectTrigger>
                  <SelectContent className="glass">
                    {categories.map(cat => (
                      <SelectItem key={cat.id} value={cat.id}>
                        <div className="flex items-center">
                          <span className="w-2 h-2 rounded-full mr-2" style={{ backgroundColor: cat.color }} />
                          {cat.name}
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="description" className="text-gray-700 dark:text-gray-300">备注</Label>
                <Input
                  id="description"
                  placeholder="选填"
                  value={newProject.description}
                  onChange={e => {
                    setNewProject({ ...newProject, description: e.target.value });
                    if (createError) setCreateError('');
                  }}
                  className="bg-white/50 dark:bg-black/20"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label className="text-gray-700 dark:text-gray-300">自定义标签</Label>
              <div className="flex gap-2">
                <Input
                  placeholder="输入标签后按回车"
                  value={newTag}
                  onChange={e => {
                    setNewTag(e.target.value);
                    if (createError) setCreateError('');
                  }}
                  onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addTag())}
                  className="bg-white/50 dark:bg-black/20"
                />
                <Button type="button" variant="secondary" onClick={addTag} className="shrink-0 active-scale">添加</Button>
              </div>
              {newProject.tags.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-3 p-3 bg-gray-50/50 dark:bg-zinc-900/50 rounded-lg border border-gray-100 dark:border-zinc-800">
                  {newProject.tags.map(tag => (
                    <Badge key={tag} variant="secondary" className="cursor-pointer hover:bg-destructive hover:text-white transition-colors group" onClick={() => removeTag(tag)}>
                      {tag}
                      <span className="ml-1 opacity-50 group-hover:opacity-100">×</span>
                    </Badge>
                  ))}
                </div>
              )}
            </div>
            {createError && (
              <p className="text-sm text-red-600 dark:text-red-400">
                {createError}
              </p>
            )}
          </div>
          <DialogFooter className="border-t border-gray-100 dark:border-zinc-800/50 pt-4">
            <Button variant="ghost" onClick={() => setIsCreateOpen(false)} className="rounded-full">取消</Button>
            <Button onClick={handleCreateProject} disabled={!newProject.name.trim() || isCreating} className="rounded-full shadow-lg shadow-primary/20 active-scale">
              {isCreating && <Loader2 className="h-4 w-4 animate-spin" />}
              {isCreating ? '创建中...' : '创建项目'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Category Management Dialog */}
      <Dialog open={isCategoryOpen} onOpenChange={setIsCategoryOpen}>
        <DialogContent className="glass sm:max-w-md">
          <DialogHeader>
            <DialogTitle>管理分类</DialogTitle>
            <DialogDescription>
              现有的全局分类属性标签。
            </DialogDescription>
          </DialogHeader>
          <ScrollArea className="h-[300px] pr-4 mt-2">
            <div className="space-y-3">
              {categories.map(cat => (
                <div key={cat.id} className="flex items-center gap-3 p-3 bg-white/50 dark:bg-black/20 rounded-xl border border-gray-100 dark:border-zinc-800 shadow-sm">
                  <span className="w-8 h-8 rounded-full flex items-center justify-center border bg-white dark:bg-zinc-900 shadow-sm">
                    <span className="w-3 h-3 rounded-full" style={{ backgroundColor: cat.color }} />
                  </span>
                  <span className="flex-1 font-medium">{cat.name}</span>
                  <Badge variant="outline" className="bg-transparent text-muted-foreground">{categoryCount[cat.id] || 0} 个项目</Badge>
                </div>
              ))}
            </div>
          </ScrollArea>
          <DialogFooter className="mt-4 border-t border-gray-100 dark:border-zinc-800/50 pt-4">
            <Button variant="outline" onClick={() => setIsCategoryOpen(false)} className="rounded-full">完成</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
