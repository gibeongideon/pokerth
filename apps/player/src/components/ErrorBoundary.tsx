import { Component, type ReactNode } from "react";

/**
 * Keeps a crash in one part of the screen (e.g. the table renderer) from
 * unmounting the whole page - which would also drop the live game connection.
 */
export class ErrorBoundary extends Component<{ children: ReactNode; label: string }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error(`${this.props.label} crashed`, error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="flex h-full min-h-[64px] flex-col items-center justify-center gap-2 p-4 text-center text-cream/70">
        <span>The {this.props.label} hit a problem. Your seat is safe.</span>
        <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => this.setState({ failed: false })}>
          Show it again
        </button>
      </div>
    );
  }
}
