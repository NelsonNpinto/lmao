import { Component, type ErrorInfo, type ReactNode } from 'react'

interface State {
  error: Error | null
}

/** Catches render errors so one broken card never blanks the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode; label?: string }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('render_error', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" className="border-border bg-surface rounded-xl border p-6">
        <p className="font-semibold">Something went wrong{this.props.label ? ` in ${this.props.label}` : ''}.</p>
        <p className="text-muted mt-1 text-sm">{this.state.error.message}</p>
        <button
          type="button"
          className="border-border hover:bg-surface-2 mt-3 rounded-md border px-3 py-1.5 text-sm"
          onClick={() => this.setState({ error: null })}
        >
          Try again
        </button>
      </div>
    )
  }
}
