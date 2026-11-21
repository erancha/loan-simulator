/** The speeds the demo plays at: the recording's own pace, and twice that. */
export type Rate = 1 | 2

/** One wait in progress: the demo time it ends at, and the timer set to reach it. */
interface Pending {
  endsAt: number
  resolve: () => void
  timer: ReturnType<typeof setTimeout> | null
}

/**
 * The demo's own time, which the replay waits on and the visitor controls: it can stop, and it
 * runs at the recording's pace or twice that. Demo time is the recording's time, so a wait of a
 * second of it takes half a second at 2×.
 *
 * - wait resolves once the demo time it names has passed, however often the clock stops or
 *   changes speed meanwhile.
 * - elapsed is the demo time passed since the clock started.
 * - subscribe tells a listener of every pause, resume and speed change.
 */
export function createDemoClock() {
  // Demo time at the last pause, resume or speed change, and the wall-clock time it was taken at.
  let base = 0
  let baseAt = Date.now()
  let running = true
  let speed: Rate = 1
  const pending = new Set<Pending>()
  const listeners = new Set<() => void>()

  const elapsed = () => (running ? base + (Date.now() - baseAt) * speed : base)

  function arm(wait: Pending) {
    if (wait.timer !== null) clearTimeout(wait.timer)
    wait.timer = null
    if (!running) return
    const left = Math.max(0, wait.endsAt - elapsed())
    wait.timer = setTimeout(() => {
      pending.delete(wait)
      wait.resolve()
    }, left / speed)
  }

  /** Fixes the demo time passed so far, applies the change, and sets every wait's timer anew. */
  function change(apply: () => void) {
    base = elapsed()
    baseAt = Date.now()
    apply()
    for (const wait of pending) arm(wait)
    for (const listener of listeners) listener()
  }

  return {
    wait(ms: number): Promise<void> {
      return new Promise((resolve) => {
        const wait: Pending = { endsAt: elapsed() + ms, resolve, timer: null }
        pending.add(wait)
        arm(wait)
      })
    },
    elapsed,
    paused: () => !running,
    rate: () => speed,
    pause() {
      change(() => {
        running = false
      })
    },
    resume() {
      change(() => {
        running = true
      })
    },
    setRate(rate: Rate) {
      change(() => {
        speed = rate
      })
    },
    subscribe(listener: () => void): () => void {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
  }
}

export type DemoClock = ReturnType<typeof createDemoClock>
