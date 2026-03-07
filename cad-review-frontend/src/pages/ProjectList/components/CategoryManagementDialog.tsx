import { useEffect, useState } from 'react';
import { Loader2, Pencil, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import * as api from '@/api';
import type { Category } from '@/types';
import axios from 'axios';

interface CategoryManagementDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    categories: Category[];
    activeCategoryId?: string;
    onActiveCategoryInvalidated?: () => void;
    onSuccess: () => Promise<void> | void;
}

const COLOR_OPTIONS = [
    '#EF1D16',
    '#18181B',
    '#2563EB',
    '#0F766E',
    '#CA8A04',
    '#7C3AED',
    '#BE123C',
    '#475569',
];

export default function CategoryManagementDialog({
    isOpen,
    onOpenChange,
    categories,
    activeCategoryId,
    onActiveCategoryInvalidated,
    onSuccess,
}: CategoryManagementDialogProps) {
    const [editingCategoryId, setEditingCategoryId] = useState<string | null>(null);
    const [name, setName] = useState('');
    const [color, setColor] = useState(COLOR_OPTIONS[0]);
    const [error, setError] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [categoryToDelete, setCategoryToDelete] = useState<Category | null>(null);
    const [isDeleting, setIsDeleting] = useState(false);

    useEffect(() => {
        if (!isOpen) return;
        setEditingCategoryId(null);
        setName('');
        setColor(COLOR_OPTIONS[0]);
        setError('');
        setCategoryToDelete(null);
        setIsSubmitting(false);
        setIsDeleting(false);
    }, [isOpen]);

    const getErrorMessage = (errorValue: unknown, fallback: string) => {
        if (axios.isAxiosError(errorValue)) {
            if (typeof errorValue.response?.data?.detail === 'string') return errorValue.response.data.detail;
            return errorValue.message || fallback;
        }
        if (errorValue instanceof Error && errorValue.message) return errorValue.message;
        return fallback;
    };

    const startCreate = () => {
        setEditingCategoryId(null);
        setName('');
        setColor(COLOR_OPTIONS[0]);
        setError('');
    };

    const startEdit = (category: Category) => {
        setEditingCategoryId(category.id);
        setName(category.name);
        setColor(category.color || COLOR_OPTIONS[0]);
        setError('');
    };

    const handleSubmit = async () => {
        const trimmedName = name.trim();
        if (!trimmedName) {
            setError('请先填写分类名称。');
            return;
        }
        try {
            setIsSubmitting(true);
            setError('');
            if (editingCategoryId) {
                await api.updateCategory(editingCategoryId, { name: trimmedName, color });
            } else {
                await api.createCategory({ name: trimmedName, color });
            }
            await onSuccess();
            startCreate();
        } catch (submitError) {
            setError(getErrorMessage(submitError, editingCategoryId ? '修改分类失败。' : '创建分类失败。'));
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleDelete = async () => {
        if (!categoryToDelete) return;
        try {
            setIsDeleting(true);
            await api.deleteCategory(categoryToDelete.id);
            if (activeCategoryId === categoryToDelete.id) {
                onActiveCategoryInvalidated?.();
            }
            await onSuccess();
            if (editingCategoryId === categoryToDelete.id) {
                startCreate();
            }
            setCategoryToDelete(null);
        } catch (deleteError) {
            setError(getErrorMessage(deleteError, '删除分类失败。'));
        } finally {
            setIsDeleting(false);
        }
    };

    return (
        <>
            <Dialog open={isOpen} onOpenChange={onOpenChange}>
                <DialogContent className="gap-6 rounded-none border-border bg-white p-8 sm:max-w-[840px]">
                    <DialogHeader>
                        <DialogTitle className="text-[20px] font-semibold text-foreground">分类管理</DialogTitle>
                    </DialogHeader>

                    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
                        <div className="border border-border bg-secondary/20">
                            <div className="flex items-center justify-between border-b border-border px-5 py-4">
                                <div>
                                    <p className="text-[15px] font-semibold text-foreground">现有分类</p>
                                    <p className="text-[12px] text-muted-foreground">共 {categories.length} 个分类</p>
                                </div>
                                <Button
                                    variant="outline"
                                    size="icon"
                                    onClick={startCreate}
                                    className="h-9 w-9 rounded-none border-border bg-white shadow-none"
                                >
                                    <Plus className="h-4 w-4" />
                                </Button>
                            </div>

                            <div className="max-h-[420px] overflow-y-auto">
                                {categories.length === 0 ? (
                                    <div className="px-5 py-10 text-center text-[13px] text-muted-foreground">
                                        暂无分类，先新建一个。
                                    </div>
                                ) : (
                                    categories.map((category) => {
                                        const isEditing = editingCategoryId === category.id;
                                        return (
                                            <div
                                                key={category.id}
                                                className={`flex items-center gap-3 border-b border-border px-5 py-4 last:border-b-0 ${isEditing ? 'bg-white' : 'bg-transparent'}`}
                                            >
                                                <span className="h-3 w-3 shrink-0 rounded-none" style={{ backgroundColor: category.color }} />
                                                <button
                                                    onClick={() => startEdit(category)}
                                                    className="flex-1 truncate text-left text-[14px] font-medium text-foreground"
                                                >
                                                    {category.name}
                                                </button>
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => startEdit(category)}
                                                    className="h-8 w-8 rounded-none"
                                                >
                                                    <Pencil className="h-4 w-4" />
                                                </Button>
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => setCategoryToDelete(category)}
                                                    className="h-8 w-8 rounded-none text-destructive hover:bg-destructive/10 hover:text-destructive"
                                                >
                                                    <Trash2 className="h-4 w-4" />
                                                </Button>
                                            </div>
                                        );
                                    })
                                )}
                            </div>
                        </div>

                        <div className="border border-border bg-white p-6">
                            <div className="mb-6 flex items-center justify-between">
                                <div>
                                    <p className="text-[16px] font-semibold text-foreground">
                                        {editingCategoryId ? '修改分类' : '新建分类'}
                                    </p>
                                    <p className="text-[13px] text-muted-foreground">
                                        设置分类名称和侧边栏显示颜色。
                                    </p>
                                </div>
                                {editingCategoryId && (
                                    <Button
                                        variant="outline"
                                        onClick={startCreate}
                                        className="rounded-none border-border bg-white shadow-none"
                                    >
                                        新建模式
                                    </Button>
                                )}
                            </div>

                            <div className="space-y-5">
                                <div className="space-y-2">
                                    <Label htmlFor="category-name" className="text-[14px] text-foreground">分类名称</Label>
                                    <Input
                                        id="category-name"
                                        value={name}
                                        onChange={(event) => {
                                            setName(event.target.value);
                                            if (error) setError('');
                                        }}
                                        placeholder="例如：住宅、商业、办公"
                                        className="h-10 rounded-none border-border bg-white shadow-none"
                                    />
                                </div>

                                <div className="space-y-2">
                                    <Label className="text-[14px] text-foreground">分类颜色</Label>
                                    <div className="flex flex-wrap gap-3">
                                        {COLOR_OPTIONS.map((option) => (
                                            <button
                                                key={option}
                                                type="button"
                                                onClick={() => setColor(option)}
                                                className={`h-9 w-9 rounded-none border ${color === option ? 'border-foreground' : 'border-border'}`}
                                                style={{ backgroundColor: option }}
                                                aria-label={`选择颜色 ${option}`}
                                            />
                                        ))}
                                    </div>
                                </div>

                                {error && (
                                    <div className="text-[13px] text-destructive">{error}</div>
                                )}

                                <div className="flex justify-end gap-3 pt-2">
                                    <Button
                                        variant="outline"
                                        onClick={() => onOpenChange(false)}
                                        className="rounded-none border-border bg-white shadow-none"
                                    >
                                        关闭
                                    </Button>
                                    <Button
                                        onClick={handleSubmit}
                                        disabled={isSubmitting}
                                        className="rounded-none bg-primary shadow-none"
                                    >
                                        {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                                        {editingCategoryId ? '保存分类' : '创建分类'}
                                    </Button>
                                </div>
                            </div>
                        </div>
                    </div>
                </DialogContent>
            </Dialog>

            <AlertDialog open={Boolean(categoryToDelete)} onOpenChange={(open) => !open && !isDeleting && setCategoryToDelete(null)}>
                <AlertDialogContent className="max-w-[520px] rounded-none border border-border bg-white p-0 shadow-lg">
                    <AlertDialogHeader className="items-start gap-3 px-7 pt-7 text-left">
                        <AlertDialogTitle className="text-[22px] font-semibold leading-none text-zinc-900">
                            删除分类
                        </AlertDialogTitle>
                        <AlertDialogDescription className="text-[14px] leading-6 text-zinc-600">
                            删除后，该分类下已有项目会失去分类归属。
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <div className="mx-7 mt-5 rounded-none border border-border bg-secondary px-4 py-3.5 text-[14px] text-zinc-700">
                        <span className="text-zinc-500">分类：</span>
                        <span className="font-medium text-zinc-900">{categoryToDelete?.name}</span>
                    </div>
                    <AlertDialogFooter className="mt-7 flex-row justify-end gap-3 border-t border-zinc-100 px-7 py-5">
                        <AlertDialogCancel
                            disabled={isDeleting}
                            className="h-10 rounded-none border-border bg-white px-6 text-[15px] font-medium text-zinc-700 hover:bg-secondary"
                        >
                            取消
                        </AlertDialogCancel>
                        <AlertDialogAction
                            onClick={handleDelete}
                            disabled={isDeleting}
                            className="h-10 rounded-none bg-red-600 px-6 text-[15px] font-semibold text-white hover:bg-red-700"
                        >
                            {isDeleting ? '删除中...' : '确认删除'}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    );
}
