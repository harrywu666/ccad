import type { ErrorInfo, ReactNode } from 'react';
import { Component } from 'react';
import { useEffect, useState } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface AppErrorBoundaryProps {
  children: ReactNode;
}

interface AppErrorBoundaryState {
  hasError: boolean;
  message: string;
}

// 功能说明：应用启动加载态回退组件，显示旋转加载动画
export function AppStartupFallback() {
  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-secondary/30">
      <div className="flex items-center gap-3 text-foreground text-sm">
        <RefreshCw className="w-4 h-4 animate-spin text-primary" />
        正在加载应用...
      </div>
    </div>
  );
}

// 功能说明：应用启动门控组件，等待浏览器渲染帧完成后显示子组件
export function AppStartupGate({ children }: { children: ReactNode }) {
  // 功能说明：应用就绪状态
  const [ready, setReady] = useState(false);

  // 功能说明：请求动画帧以确保DOM就绪后显示内容
  useEffect(() => {
    const raf = window.requestAnimationFrame(() => setReady(true));
    return () => window.cancelAnimationFrame(raf);
  }, []);

  if (!ready) {
    return <AppStartupFallback />;
  }
  return <>{children}</>;
}

// 功能说明：应用错误边界类组件，捕获并处理React渲染错误
export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = {
    hasError: false,
    message: '',
  };

  // 功能说明：静态方法，从错误中派生错误状态
  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return {
      hasError: true,
      message: error?.message || '页面加载失败',
    };
  }

  // 功能说明：捕获错误并记录到控制台
  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('AppErrorBoundary captured an error:', error, errorInfo);
  }

  // 功能说明：渲染子组件或错误提示界面
  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div className="min-h-screen w-full flex items-center justify-center bg-secondary/30 p-6">
        <div className="max-w-lg w-full border border-destructive/30 bg-white p-6 flex flex-col gap-4">
          <div className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="w-4 h-4" />
            <h1 className="text-base font-semibold">页面加载失败</h1>
          </div>
          <p className="text-sm text-muted-foreground break-words">
            {this.state.message || '发生未知错误，请刷新页面重试。'}
          </p>
          <button
            type="button"
            className="w-fit px-4 py-2 text-sm bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
            onClick={() => window.location.reload()}
          >
            刷新页面
          </button>
        </div>
      </div>
    );
  }
}
