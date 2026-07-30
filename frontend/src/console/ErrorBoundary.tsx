import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, House, RotateCcw } from "lucide-react";


interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  failed: boolean;
}


export class ConsoleErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo): void {
    // Runtime telemetry captures the active trace; the UI never exposes stack details.
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="console-boundary" role="alert">
        <AlertTriangle size={28} aria-hidden="true" />
        <h1>当前工作区无法显示</h1>
        <dl>
          <div><dt>影响</dt><dd>当前页面已停止渲染，未自动重放任何命令。</dd></div>
          <div><dt>下一步</dt><dd>重新载入当前页面；若仍失败，请从任务中心查看处理记录。</dd></div>
        </dl>
        <div>
          <button type="button" className="wb-button wb-button-primary" onClick={() => window.location.reload()}><RotateCcw size={15} aria-hidden="true" />重新载入</button>
          <a className="wb-button" href="/console/"><House size={15} aria-hidden="true" />返回业务概览</a>
        </div>
      </main>
    );
  }
}
