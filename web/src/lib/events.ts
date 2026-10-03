// The event contract from infrachat/trace.py (docs/DEMO-PLAN.md § Events). One reducer
// folds a stream of these into one message, so a recorded replay and a live SSE stream
// render identically: the UI never knows which one it's watching.

export type Hit = {
  rank: number
  tag: string
  chunk_id: string
  source: "kubernetes" | "docker"
  doc: string
  lines: string
  score: number
  dense_rank?: number | null
  keyword_rank?: number | null
}

export type Citation = {
  n: number
  tag: string
  source: string
  doc: string
  lines: string
  passages: string[]   // what the model was shown under this tag
  url: string | null   // the page on GitHub at the indexed commit; a citation click opens it
}

export type TraceEvent =
  | { type: "start"; data: { question: string; config: { hybrid: boolean; rerank: boolean; rewrite: boolean; floor: number } } }
  | { type: "rewrite"; data: { query: string; changed: boolean; ms: number } }
  | { type: "embed"; data: { ms: number } }
  | { type: "retrieve.dense"; data: { count?: number; hits?: Hit[]; ms: number } }
  | { type: "retrieve.keyword"; data: { count: number; ms: number } }
  | { type: "fuse"; data: { hits: Hit[] } }
  | { type: "rerank"; data: { active: boolean; moves: unknown[]; ms: number; hits: Hit[] } }
  | { type: "gate.floor"; data: { passed: boolean; top_score: number | null; floor: number; margin: number | null } }
  | { type: "prompt"; data: { tokens_est: number } }
  | { type: "llm.reasoning"; data: { delta: string } }
  | { type: "llm.token"; data: { delta: string } }
  | { type: "gate.citations"; data: { passed: boolean; cited: string[]; invented: string[]; said_not_in_docs: boolean } }
  | { type: "answer"; data: { text: string; citations: Citation[] } }
  | { type: "refusal"; data: { gate: "floor" | "citation"; reason: string; detail: string } }
  | { type: "done"; data: { ms_total: number; llm_ms?: number | null; usage?: { total_tokens?: number } | null } }
  | { type: "error"; data: { kind: string; message: string } }

export type StepState = "waiting" | "running" | "passed" | "refused" | "skipped"

export type Message = {
  id: string
  question: string
  source: "replay" | "live"
  hybrid: boolean
  searchMs: number
  candidates: number
  excerpts: Hit[]
  arms: Record<string, { dense_rank?: number | null; keyword_rank?: number | null }>
  floor: { state: StepState; score: number | null; threshold: number }
  model: { state: StepState; reasoning: string; promptTokens: number }
  cite: { state: StepState; cited: string[]; invented: string[]; saidNotInDocs: boolean }
  draft: string
  answer: { text: string; citations: Citation[] } | null
  refusal: { gate: "floor" | "citation"; detail: string } | null
  error: string | null
  totalMs: number | null
  tokens: number | null
}

export function newMessage(id: string, question: string, source: Message["source"]): Message {
  return {
    id, question, source, hybrid: false, searchMs: 0, candidates: 0, excerpts: [], arms: {},
    floor: { state: "running", score: null, threshold: 0.65 },
    model: { state: "waiting", reasoning: "", promptTokens: 0 },
    cite: { state: "waiting", cited: [], invented: [], saidNotInDocs: false },
    draft: "", answer: null, refusal: null, error: null, totalMs: null, tokens: null,
  }
}

export function reduce(m: Message, e: TraceEvent): Message {
  switch (e.type) {
    case "start":
      return { ...m, hybrid: e.data.config.hybrid, floor: { ...m.floor, threshold: e.data.config.floor } }
    case "embed":
    case "retrieve.keyword":
      return { ...m, searchMs: m.searchMs + e.data.ms }
    case "retrieve.dense":
      return { ...m, searchMs: m.searchMs + e.data.ms, candidates: e.data.count ?? e.data.hits?.length ?? 0 }
    case "fuse":
      // The fused list carries each passage's rank in the two arms; the reranked list
      // (what the model reads) doesn't, so keep them to label keyword-lifted passages.
      return { ...m, arms: Object.fromEntries(e.data.hits.map((h) => [h.chunk_id, { dense_rank: h.dense_rank, keyword_rank: h.keyword_rank }])) }
    case "rerank":
      return { ...m, excerpts: e.data.hits.map((h) => ({ ...h, ...m.arms[h.chunk_id] })) }
    case "gate.floor":
      return {
        ...m,
        floor: { state: e.data.passed ? "passed" : "refused", score: e.data.top_score, threshold: e.data.floor },
        model: { ...m.model, state: e.data.passed ? "running" : "skipped" },
        cite: { ...m.cite, state: e.data.passed ? "waiting" : "skipped" },
      }
    case "prompt":
      return { ...m, model: { ...m.model, promptTokens: e.data.tokens_est } }
    case "llm.reasoning":
      return { ...m, model: { ...m.model, reasoning: m.model.reasoning + e.data.delta } }
    case "llm.token":
      return { ...m, draft: m.draft + e.data.delta, cite: { ...m.cite, state: "running" } }
    case "gate.citations":
      return {
        ...m,
        model: { ...m.model, state: "passed" },
        cite: {
          state: e.data.passed ? "passed" : "refused", cited: e.data.cited,
          invented: e.data.invented, saidNotInDocs: e.data.said_not_in_docs,
        },
      }
    case "answer":
      return { ...m, answer: e.data }
    case "refusal":
      return { ...m, refusal: { gate: e.data.gate, detail: e.data.detail } }
    case "done":
      return { ...m, totalMs: e.data.ms_total, tokens: e.data.usage?.total_tokens ?? null }
    case "error":
      return { ...m, error: e.data.message, totalMs: m.totalMs ?? 0 }
    default:
      return m
  }
}

export const isFinished = (m: Message) => m.totalMs !== null
