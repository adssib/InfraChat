// Live mode: the backend session on Azure (or `infrachat serve` locally). POST a
// question, read Server-Sent Events back. EventSource can't send a POST body, so the
// stream is parsed by hand from fetch.

import type { TraceEvent } from "./events"

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000"

/** True when a backend session is up. Short timeout: offline should feel instant. */
export async function backendIsUp(): Promise<boolean> {
  try {
    const r = await fetch(`${API_URL}/healthz`, { signal: AbortSignal.timeout(2500) })
    return r.ok
  } catch {
    return false
  }
}

export async function askLive(question: string, onEvent: (e: TraceEvent) => void, signal: AbortSignal): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${API_URL}/api/ask`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "text/event-stream" },
      body: JSON.stringify({ question }),
      signal,
    })
  } catch {
    if (!signal.aborted) onEvent({ type: "error", data: { kind: "network", message: "Can't reach the backend. The live session may have ended." } })
    return
  }
  if (!res.ok || !res.body) {
    const message =
      res.status === 429 ? "Too many questions this minute. Wait a few seconds and ask again."
      : res.status === 400 ? "Questions can be up to 500 characters."
      : `The backend answered ${res.status}.`
    onEvent({ type: "error", data: { kind: "http", message } })
    return
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ""
  let pendingCR = false
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      // SSE lines may end in \r\n, \n or \r (Litestar sends \r\n). Normalise to \n,
      // holding back a trailing \r in case its \n arrives in the next chunk.
      let text: string = (pendingCR ? "\r" : "") + value
      pendingCR = text.endsWith("\r")
      if (pendingCR) text = text.slice(0, -1)
      buffer += text.replace(/\r\n?/g, "\n")
      let end: number
      // One SSE message per blank line; `event:` names it, `data:` carries the JSON.
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, end)
        buffer = buffer.slice(end + 2)
        let type = "message"
        const data: string[] = []
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) type = line.slice(6).trim()
          else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""))
        }
        if (data.length) onEvent({ type, data: JSON.parse(data.join("\n")) } as TraceEvent)
      }
    }
  } catch {
    if (!signal.aborted) onEvent({ type: "error", data: { kind: "network", message: "The connection dropped mid-answer." } })
  }
}
