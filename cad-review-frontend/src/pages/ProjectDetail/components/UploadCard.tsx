// src/pages/ProjectDetail/components/UploadCard.tsx
import { CloudUpload, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';

interface UploadCardProps {
    title: string;
    description: string;
    uploadText: string;
    uploading: boolean;
    onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
    accept?: string;
    multiple?: boolean;
    className?: string;
    compact?: boolean;
    uploadProgress?: number;
    uploadProgressText?: string;
    buttonClassName?: string;
}

export default function UploadCard({
    title,
    description,
    uploadText,
    uploading,
    onUpload,
    accept = "image/*",
    multiple = false,
    className = '',
    compact = false,
    uploadProgress = 0,
    uploadProgressText,
    buttonClassName = 'bg-primary hover:bg-primary/90 text-white'
}: UploadCardProps) {
    return (
        <div className={`flex flex-col ${compact ? 'gap-3 p-4' : 'gap-6 p-8'} bg-secondary/30 border border-border rounded-none w-full max-w-[436px] ${className}`}>
            <div className={compact ? 'text-center' : ''}>
                <h2 className={`${compact ? 'text-[18px] mb-1' : 'text-[22px] mb-2'} font-semibold font-sans text-foreground`}>{title}</h2>
                {!compact && (
                    <p className="text-[13px] text-muted-foreground font-sans leading-relaxed">
                        {description}
                    </p>
                )}
            </div>

            <div className={`group relative border border-dashed border-border/80 bg-white text-center hover:border-primary/50 transition-colors duration-300 ${compact ? 'p-4' : 'p-10'}`}>
                <CloudUpload className={`${compact ? 'h-7 w-7 mb-2' : 'h-12 w-12 mb-4'} mx-auto text-primary group-hover:scale-110 transition-transform duration-300`} />
                <h3 className={`${compact ? 'text-[13px] mb-2' : 'text-[15px] mb-2'} font-sans font-semibold text-foreground`}>
                    拖拽或点击上传
                </h3>
                {!compact && (
                    <p className="text-[12px] text-muted-foreground mb-6 font-sans">
                        {multiple ? '支持拖拽多份文件' : '支持单个文件压缩包或图片'}
                    </p>
                )}

                <Label className="cursor-pointer block">
                    <Input
                        type="file"
                        accept={accept}
                        multiple={multiple}
                        className="hidden"
                        onChange={onUpload}
                        disabled={uploading}
                    />
                    <Button asChild className={`rounded-none shadow-none text-[14px] w-full ${buttonClassName} ${compact ? 'h-10 px-4' : 'px-8 py-5 h-auto'}`}>
                        <span>
                            {uploading ? (
                                <><RefreshCw className="mr-2 h-4 w-4 animate-spin" /> 处理中...</>
                            ) : (
                                uploadText
                            )}
                        </span>
                    </Button>
                </Label>

                {uploading && (
                    <div className="mt-3">
                        <div className="mb-1 flex items-center justify-between text-[12px] text-muted-foreground">
                            <span>{uploadProgressText || '上传进度'}</span>
                            <span>{uploadProgress}%</span>
                        </div>
                        <Progress
                            value={uploadProgress}
                            className="h-1.5 bg-secondary [&>div]:bg-primary"
                        />
                    </div>
                )}
            </div>
        </div>
    );
}
