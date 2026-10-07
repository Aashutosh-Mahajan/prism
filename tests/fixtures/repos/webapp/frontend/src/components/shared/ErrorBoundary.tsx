import { Component, ReactNode } from 'react';

interface State {
  failed: boolean;
}

export default class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return <h2>Something went wrong</h2>;
    }
    return this.props.children;
  }
}
