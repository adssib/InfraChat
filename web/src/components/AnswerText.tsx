// Renders exactly what the model produces: paragraphs, fenced code, inline code, and
// citation tags. Tags appear raw while the text is an unverified draft; once gate 2 has
// passed they become numbered chips (the one moment of motion in the UI).

import { ExternalLink } from "lucide-react"
import { Fragment, type ReactNode } from "react"

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { Citation } from "@/lib/events"
import { cn } from "@/lib/utils"

const TAG = /\[((?:kubernetes|docker):[^\]\s]+)\]/g

function inline(text: string, cites: Map<string, Citation> | null, key: string): ReactNode[] {
  const out: ReactNode[] = []
  text.split(/(`[^`\n]+`)/g).forEach((part, i) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      out.push(
        <code key={`${key}c${i}`} className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[0.85em]">
          {part.slice(1, -1)}
        </code>,
      )
      return
    }
    let last = 0
    for (const m of part.matchAll(TAG)) {
      out.push(part.slice(last, m.index))
      const c = cites?.get(m[1])
      out.push(
        c ? (
          <Chip key={`${key}t${i}-${m.index}`} c={c} />
        ) : (
          <span key={`${key}t${i}-${m.index}`} className="font-mono text-[0.8em] text-muted-foreground">
            {m[0]}
          </span>
        ),
      )
      last = (m.index ?? 0) + m[0].length
    }
    out.push(part.slice(last))
  })
  return out
}

// A citation is a link: one click opens the cited page on GitHub, at the commit that was
// indexed. Pages, not lines — chunk line numbers count the cleaned text (infrachat/links.py).
function Chip({ c }: { c: Citation }) {
  const cls = "chip-in mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full border border-primary/40 bg-primary/10 px-1.5 align-[0.1em] font-mono text-[11px] font-medium text-primary transition-colors hover:bg-primary/25 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {c.url ? (
          <a href={c.url} target="_blank" rel="noreferrer" className={cls} aria-label={`Source ${c.n}: ${c.doc}, opens GitHub`}>{c.n}</a>
        ) : (
          <span className={cls}>{c.n}</span>
        )}
      </TooltipTrigger>
      <TooltipContent side="top" className="flex items-center gap-1.5 font-mono text-xs">
        {c.doc}
        {c.url && <ExternalLink className="size-3 opacity-70" aria-hidden />}
      </TooltipContent>
    </Tooltip>
  )
}

export function AnswerText({
  text,
  citations,
  draft,
}: {
  text: string
  citations?: Citation[]
  draft?: boolean
}) {
  const cites = citations ? new Map(citations.map((c) => [c.tag, c])) : null
  const blocks = text.split(/(```[\s\S]*?(?:```|$))/g)

  return (
    <div className={cn("space-y-3 text-[15px] leading-7", draft && "text-foreground/55")}>
      {blocks.map((block, bi) => {
        if (block.startsWith("```")) {
          const body = block.replace(/^```[^\n]*\n?/, "").replace(/```$/, "")
          const lang = block.match(/^```(\w+)/)?.[1]
          return (
            <pre
              key={bi}
              className="overflow-x-auto rounded-xl border bg-card px-4 py-3 font-mono text-[13px] leading-6"
              aria-label={lang ? `${lang} code` : "code"}
            >
              <code>{body.replace(/\n$/, "")}</code>
            </pre>
          )
        }
        return block
          .split(/\n{2,}/)
          .filter((p) => p.trim())
          .map((para, pi) => (
            <p key={`${bi}-${pi}`} className="text-pretty">
              {para.split(/\s*\n/).map((line, li, all) => (
                <Fragment key={li}>
                  {inline(line, cites, `${bi}-${pi}-${li}`)}
                  {li < all.length - 1 && <br />}
                </Fragment>
              ))}
            </p>
          ))
      })}
      {draft && <span className="caret" aria-hidden />}
    </div>
  )
}
