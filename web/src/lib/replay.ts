// Offline mode: play a recorded run (scripts/record_replays.py) back at its real pace.
// Same events the live API will stream, so the rest of the UI can't tell the difference.

import type { TraceEvent } from "./events"

type Recording = { question: string; recorded: string; events: (TraceEvent & { t: number })[] }

const base = import.meta.env.BASE_URL

let index: Promise<Record<string, string>> | null = null

export function replayIndex(): Promise<Record<string, string>> {
  index ??= fetch(`${base}replays/index.json`).then((r) => (r.ok ? r.json() : {}))
  return index
}

// Groq streams the whole answer in a fraction of a second. Recorded at that pace, a draft
// would appear in one frame, so stream pieces are spaced at least this far apart. Pipeline
// steps keep their real timing.
const MIN_STREAM_GAP_MS = 14

export async function playReplay(
  question: string,
  onEvent: (e: TraceEvent) => void,
  signal: AbortSignal,
): Promise<boolean> {
  const file = (await replayIndex())[question]
  if (!file) return false
  const rec: Recording = await fetch(`${base}replays/${file}`).then((r) => r.json())

  let clock = 0
  for (const e of rec.events) {
    const streamed = e.type === "llm.token" || e.type === "llm.reasoning"
    const at = streamed ? Math.max(e.t, clock + MIN_STREAM_GAP_MS) : Math.max(e.t, clock)
    await sleep(at - clock, signal)
    clock = at
    if (signal.aborted) return true
    onEvent(e)
  }
  return true
}

function sleep(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    if (ms <= 0 || signal.aborted) return resolve()
    const id = setTimeout(resolve, ms)
    signal.addEventListener("abort", () => { clearTimeout(id); resolve() }, { once: true })
  })
}
