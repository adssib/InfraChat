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
      className="glass flex items-end gap-2 rounded-2xl p-2 pl-4 transition-shadow focus-within:shadow-[inset_0_1px_0_var(--glass-highlight),0_0_0_1px_rgb(41_159_255/0.45),0_10px_40px_-12px_rgb(41_159_255/0.35)]"
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
        className={cn("accent-gradient size-9 shrink-0 rounded-full text-white shadow-[0_4px_18px_-4px_rgb(41_159_255/0.7)] transition-[transform,opacity] hover:scale-105 active:scale-95 disabled:opacity-35 disabled:shadow-none")}
      >
        <ArrowUp className="size-4" strokeWidth={2.5} />
      </Button>
    </form>
  )
}
