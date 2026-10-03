import { ArrowUp } from "lucide-react"
import { useRef, useState, type FormEvent, type KeyboardEvent } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export function Composer({ onSend, busy, autoFocus }: { onSend: (q: string) => void; busy: boolean; autoFocus?: boolean }) {
  const [value, setValue] = useState("")
  const ref = useRef<HTMLTextAreaElement>(null)

  const send = (e?: FormEvent) => {
    e?.preventDefault()
    const q = value.trim()
    if (!q || busy) return
    onSend(q)
    setValue("")
    if (ref.current) ref.current.style.height = ""
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) send(e)
  }

  return (
    <form
      onSubmit={send}
      className="flex items-end gap-2 rounded-2xl border border-input bg-card p-2 pl-4 shadow-[0_1px_0_rgb(255_255_255/0.03)_inset] focus-within:border-ring"
    >
      <label htmlFor="question" className="sr-only">Your question</label>
      <textarea
        id="question"
        ref={ref}
        rows={1}
        value={value}
        autoFocus={autoFocus}
        maxLength={500}
        placeholder="Ask about Kubernetes or Docker"
        onChange={(e) => {
          setValue(e.target.value)
          e.target.style.height = ""
          e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`
        }}
        onKeyDown={onKey}
        className="max-h-[200px] min-h-9 flex-1 resize-none bg-transparent py-1.5 text-[15px] leading-6 outline-none placeholder:text-muted-foreground"
      />
      <Button
        type="submit"
        size="icon"
        disabled={!value.trim() || busy}
        aria-label="Send"
        className={cn("size-9 shrink-0 rounded-full")}
      >
        <ArrowUp className="size-4" strokeWidth={2.5} />
      </Button>
    </form>
  )
}
