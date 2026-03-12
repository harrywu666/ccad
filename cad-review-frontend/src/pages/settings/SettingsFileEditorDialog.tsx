import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

const textareaClassName =
  'min-h-[420px] w-full resize-y border border-border bg-secondary px-4 py-4 text-[14px] leading-7 text-foreground outline-none transition-colors focus:border-primary';

interface SettingsFileEditorDialogProps {
  open: boolean;
  title: string;
  description: string;
  fileLabel?: string;
  statusLabel?: string;
  statusTone?: 'warning' | 'success';
  value: string;
  onChange: (value: string) => void;
  onOpenChange: (open: boolean) => void;
  onSave: () => Promise<void> | void;
  saveDisabled?: boolean;
  saving?: boolean;
  saveLabel?: string;
  onRestoreDefault?: () => void;
  restoreDisabled?: boolean;
}

export default function SettingsFileEditorDialog({
  open,
  title,
  description,
  fileLabel,
  statusLabel,
  statusTone = 'warning',
  value,
  onChange,
  onOpenChange,
  onSave,
  saveDisabled = false,
  saving = false,
  saveLabel = '保存',
  onRestoreDefault,
  restoreDisabled = false,
}: SettingsFileEditorDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(92vw,1080px)] max-w-[1080px] rounded-none border border-border bg-white p-0 gap-0">
        <div className="border-b border-border/80 px-7 py-6">
          <DialogHeader className="space-y-3 text-left">
            <div className="flex flex-wrap items-center gap-3">
              <DialogTitle className="text-[22px] font-semibold text-foreground">{title}</DialogTitle>
              {fileLabel ? (
                <Badge variant="outline" className="rounded-none">
                  {fileLabel}
                </Badge>
              ) : null}
              {statusLabel ? (
                <Badge
                  variant="secondary"
                  className={`rounded-none ${
                    statusTone === 'success'
                      ? 'border border-emerald-300 bg-emerald-50 text-emerald-900'
                      : 'border border-amber-300 bg-amber-50 text-amber-900'
                  }`}
                >
                  {statusLabel}
                </Badge>
              ) : null}
            </div>
            <DialogDescription className="max-w-[900px] text-[14px] leading-7 text-muted-foreground">
              {description}
            </DialogDescription>
          </DialogHeader>
        </div>

        <div className="px-7 py-6">
          <textarea
            value={value}
            onChange={event => onChange(event.target.value)}
            className={`${textareaClassName} rounded-none`}
          />
        </div>

        <DialogFooter className="border-t border-border/80 px-7 py-5">
          {onRestoreDefault ? (
            <Button
              type="button"
              variant="outline"
              className="rounded-none"
              onClick={onRestoreDefault}
              disabled={restoreDisabled || saving}
            >
              恢复默认
            </Button>
          ) : null}
          <Button
            type="button"
            variant="outline"
            className="rounded-none"
            onClick={() => onOpenChange(false)}
          >
            取消
          </Button>
          <Button
            type="button"
            className="rounded-none"
            onClick={() => void onSave()}
            disabled={saveDisabled || saving}
          >
            {saving ? '保存中...' : saveLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
