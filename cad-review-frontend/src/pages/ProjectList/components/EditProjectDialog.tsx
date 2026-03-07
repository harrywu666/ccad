import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
} from '@/components/ui/dialog';
import * as api from '@/api';
import type { Category, Project } from '@/types';
import axios from 'axios';

interface EditProjectDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    project: Project | null;
    categories: Category[];
    onSuccess: () => void;
}

export default function EditProjectDialog({
    isOpen,
    onOpenChange,
    project,
    categories,
    onSuccess,
}: EditProjectDialogProps) {
    const [form, setForm] = useState({ name: '', category: '' });
    const [editError, setEditError] = useState('');
    const [isSaving, setIsSaving] = useState(false);

    useEffect(() => {
        if (!project || !isOpen) return;
        setForm({
            name: project.name ?? '',
            category: project.category ?? '',
        });
        setEditError('');
        setIsSaving(false);
    }, [project, isOpen]);

    const getErrorMessage = (error: unknown, fallback: string) => {
        if (axios.isAxiosError(error)) {
            if (typeof error.response?.data?.detail === 'string') return error.response.data.detail;
            if (error.code === 'ERR_NETWORK') return '无法连接后端服务，请确认后端已启动。';
            return error.message || fallback;
        }
        if (error instanceof Error && error.message) return error.message;
        return fallback;
    };

    const handleSave = async () => {
        if (!project) return;
        if (!form.name.trim()) {
            setEditError('请先填写项目名称。');
            return;
        }
        try {
            setEditError('');
            setIsSaving(true);
            await api.updateProject(project.id, {
                name: form.name.trim(),
                category: form.category || undefined,
            });
            onOpenChange(false);
            onSuccess();
        } catch (error) {
            setEditError(getErrorMessage(error, '更新项目失败，请稍后重试。'));
            console.error('更新项目失败:', error);
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open) => {
                onOpenChange(open);
                if (!open) {
                    setEditError('');
                    setIsSaving(false);
                }
            }}
        >
            <DialogContent className="bg-white border-border rounded-none p-8 gap-6 sm:max-w-[500px]">
                <DialogHeader>
                    <DialogTitle className="text-[18px] font-sans font-medium text-foreground">编辑项目</DialogTitle>
                </DialogHeader>
                <div className="space-y-6">
                    <div className="space-y-2">
                        <Label htmlFor="edit-name" className="text-[14px] text-foreground font-sans">
                            项目名称 <span className="text-primary">*</span>
                        </Label>
                        <Input
                            id="edit-name"
                            placeholder="请输入项目名称"
                            value={form.name}
                            onChange={e => {
                                setForm({ ...form, name: e.target.value });
                                if (editError) setEditError('');
                            }}
                            className="bg-white border-border rounded-none h-10 text-[14px] focus-visible:ring-1 focus-visible:ring-primary shadow-none"
                        />
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor="edit-category" className="text-[14px] text-foreground font-sans">项目分类</Label>
                        <Select value={form.category} onValueChange={v => {
                            setForm({ ...form, category: v });
                            if (editError) setEditError('');
                        }}>
                            <SelectTrigger className="bg-white border-border rounded-none h-10 shadow-none text-[14px]">
                                <SelectValue placeholder="选择分类" />
                            </SelectTrigger>
                            <SelectContent className="bg-white border-border rounded-none shadow-sm">
                                {categories.map(cat => (
                                    <SelectItem key={cat.id} value={cat.id} className="text-[14px] rounded-none cursor-pointer">
                                        {cat.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    {editError && (
                        <p className="text-[14px] text-primary">{editError}</p>
                    )}
                </div>
                <DialogFooter className="pt-2">
                    <Button
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                        className="rounded-none border-border hover:bg-secondary text-[14px] font-sans font-medium bg-white"
                    >
                        取消
                    </Button>
                    <Button
                        onClick={handleSave}
                        disabled={!form.name.trim() || isSaving}
                        className="rounded-none bg-primary hover:bg-primary/90 text-primary-foreground text-[14px] font-sans font-medium"
                    >
                        {isSaving && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                        {isSaving ? '保存中...' : '保存修改'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
