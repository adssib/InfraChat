// Retrieval and gate 1 finish in ~30 ms, too fast to see. This holds each visible step on
// screen long enough to read, by spacing the events that change the trace. Only the
// presentation is paced: the timings the trace prints are the real ones from the backend.

import type { TraceEvent } from "./events"

// Minimum time since the previous paced event before this one is shown. Events not listed
// (embed, the arm counts, tokens) pass straight through, but always in order.
const HOLD_MS: Partial<Record<TraceEvent["type"], number>> = {
  rerank: 650,          // "Searching…" → search done, passages listed
  "gate.floor": 500,    // the similarity meter fills
  prompt: 300,          // the model starts reading
  "gate.citations": 350,
  answer: 250,
  refusal: 250,
}

export function paced(onEvent: (e: TraceEvent) => void, signal: AbortSignal): (e: TraceEvent) => void {
  let queue = Promise.resolve()
  let last = performance.now()
  return (e) => {
    queue = queue.then(async () => {
      const hold = HOLD_MS[e.type] ?? 0
      const wait = last + hold - performance.now()
      if (hold && wait > 0) await new Promise((r) => setTimeout(r, wait))
      if (signal.aborted) return
      if (hold) last = performance.now()
      onEvent(e)
    })
  }
}
