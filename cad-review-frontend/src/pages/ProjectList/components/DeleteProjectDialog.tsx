import { Loader2, TriangleAlert } from 'lucide-react';
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

interface DeleteProjectDialogProps {
    open: boolean;
    projectName: string;
    deleting: boolean;
    onOpenChange: (open: boolean) => void;
    onConfirm: () => void;
}

export default function DeleteProjectDialog({
    open,
    projectName,
    deleting,
    onOpenChange,
    onConfirm,
}: DeleteProjectDialogProps) {
    return (
        <AlertDialog open={open} onOpenChange={(nextOpen) => !deleting && onOpenChange(nextOpen)}>
            <AlertDialogContent
                className="max-w-[560px] rounded-none border border-border bg-white p-0 shadow-lg"
            >
                <AlertDialogHeader className="items-start gap-4 px-7 pt-7 text-left">
                    <div className="flex size-11 items-center justify-center rounded-none bg-red-50 text-red-600">
                        <TriangleAlert className="size-5" />
                    </div>
                    <div className="space-y-2">
                        <AlertDialogTitle className="text-[22px] font-semibold leading-none text-zinc-900">
                            删除项目
                        </AlertDialogTitle>
                        <AlertDialogDescription className="text-[14px] leading-6 text-zinc-600">
                            删除后不可恢复，项目下的图纸、目录、审核记录都会一并清除。
                        </AlertDialogDescription>
                    </div>
                </AlertDialogHeader>

                <div className="mx-7 mt-5 rounded-none border border-border bg-secondary px-4 py-3.5 text-[14px] text-zinc-700">
                    <span className="text-zinc-500">项目：</span>
                    <span className="font-medium text-zinc-900">{projectName}</span>
                </div>

                <AlertDialogFooter className="mt-7 flex-row justify-end gap-3 border-t border-zinc-100 px-7 py-5">
                    <AlertDialogCancel
                        disabled={deleting}
                        className="h-10 rounded-none border-border bg-white px-6 text-[15px] font-medium text-zinc-700 hover:bg-secondary"
                    >
                        取消
                    </AlertDialogCancel>
                    <AlertDialogAction
                        onClick={onConfirm}
                        disabled={deleting}
                        className="h-10 rounded-none bg-red-600 px-6 text-[15px] font-semibold text-white hover:bg-red-700"
                    >
                        {deleting && <Loader2 className="mr-1 size-4 animate-spin" />}
                        {deleting ? '删除中...' : '确认删除'}
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
}
