import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { CARD_FAILED } from './copy.ts'

interface Props {
  children: ReactNode
}

/**
 * Contains a failure to build or render the recommendation card to the card pane, so the chat
 * keeps working; the error is logged.
 */
export class CardBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('the recommendation card failed', error, info)
  }

  render() {
    return this.state.failed ? <p role="alert">{CARD_FAILED}</p> : this.props.children
  }
}
