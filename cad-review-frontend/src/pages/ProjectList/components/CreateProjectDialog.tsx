import { useState } from 'react';
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
import type { Category } from '@/types';
import axios from 'axios';

interface CreateProjectDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    categories: Category[];
    onSuccess: () => void;
}

export default function CreateProjectDialog({ isOpen, onOpenChange, categories, onSuccess }: CreateProjectDialogProps) {
    const [newProject, setNewProject] = useState({ name: '', category: '' });
    const [createError, setCreateError] = useState('');
    const [isCreating, setIsCreating] = useState(false);

    const getErrorMessage = (error: unknown, fallback: string) => {
        if (axios.isAxiosError(error)) {
            if (typeof error.response?.data?.detail === 'string') return error.response.data.detail;
            if (error.code === 'ERR_NETWORK') return '无法连接后端服务，请确认后端已启动。';
            return error.message || fallback;
        }
        if (error instanceof Error && error.message) return error.message;
        return fallback;
    };

    const handleCreate = async () => {
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
            });
            onOpenChange(false);
            setNewProject({ name: '', category: '' });
            onSuccess();
        } catch (error) {
            setCreateError(getErrorMessage(error, '创建项目失败，请稍后重试。'));
            console.error('创建项目失败:', error);
        } finally {
            setIsCreating(false);
        }
    };

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open) => {
                onOpenChange(open);
                if (!open) {
                    setCreateError('');
                    setIsCreating(false);
                }
            }}
        >
            <DialogContent className="bg-white border-border rounded-none p-8 gap-6 sm:max-w-[500px]">
                <DialogHeader>
                    <DialogTitle className="text-[18px] font-sans font-medium text-foreground">新建审核项目</DialogTitle>
                </DialogHeader>
                <div className="space-y-6">
                    <div className="space-y-2">
                        <Label htmlFor="name" className="text-[14px] text-foreground font-sans">
                            项目名称 <span className="text-primary">*</span>
                        </Label>
                        <Input
                            id="name"
                            autoComplete="off"
                            placeholder="例如：上海某某旗舰店室内方案..."
                            value={newProject.name}
                            onChange={e => {
                                setNewProject({ ...newProject, name: e.target.value });
                                if (createError) setCreateError('');
                            }}
                            className="bg-white border-border rounded-none h-10 text-[14px] focus-visible:ring-1 focus-visible:ring-primary shadow-none"
                        />
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor="category" className="text-[14px] text-foreground font-sans">项目分类</Label>
                        <Select value={newProject.category} onValueChange={v => {
                            setNewProject({ ...newProject, category: v });
                            if (createError) setCreateError('');
                        }}>
                            <SelectTrigger className="bg-white border-border rounded-none h-10 shadow-none text-[14px]">
                                <SelectValue placeholder="选择分类" />
                            </SelectTrigger>
                            <SelectContent position="popper" className="bg-white border-border rounded-none shadow-sm">
                                {categories.map(cat => (
                                    <SelectItem key={cat.id} value={cat.id} className="text-[14px] rounded-none cursor-pointer">
                                        {cat.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    {createError && (
                        <p className="text-[14px] text-primary">
                            {createError}
                        </p>
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
                        onClick={handleCreate}
                        disabled={!newProject.name.trim() || isCreating}
                        className="rounded-none bg-primary hover:bg-primary/90 text-primary-foreground text-[14px] font-sans font-medium"
                    >
                        {isCreating && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                        {isCreating ? '创建中...' : '确认创建'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
