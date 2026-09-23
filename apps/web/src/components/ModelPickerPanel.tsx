import { Check, ChevronLeft, ChevronRight, Rocket } from 'lucide-react'

export type ServiceId = 'claude' | 'chatgpt' | 'gemini' | 'antigravity'
export type ModelView = 'services' | ServiceId
export type SelectedModel = { service: ServiceId; modelId: string }

export const SERVICES: { id: ServiceId; label: string; icon: string | null }[] = [
  { id: 'claude', label: 'Claude', icon: '/models/claude.svg' },
  { id: 'chatgpt', label: 'ChatGPT', icon: '/models/chatgpt.svg' },
  { id: 'gemini', label: 'Gemini', icon: '/models/gemini.svg' },
  // No official Antigravity mark was available to fetch — Rocket is a stand-in, not a real logo.
  { id: 'antigravity', label: 'Antigravity', icon: null },
]

export const MODELS_BY_SERVICE: Record<ServiceId, { id: string; label: string }[]> = {
  claude: [
    { id: 'fable-5', label: 'Fable 5' },
    { id: 'opus-5', label: 'Opus 5' },
    { id: 'sonnet-5', label: 'Sonnet 5' },
    { id: 'haiku-4.5', label: 'Haiku 4.5' },
  ],
  chatgpt: [
    { id: 'gpt-5', label: 'GPT-5' },
    { id: 'gpt-5-mini', label: 'GPT-5 mini' },
    { id: 'o3', label: 'o3' },
  ],
  gemini: [
    { id: 'gemini-3-pro', label: 'Gemini 3 Pro' },
    { id: 'gemini-3-flash', label: 'Gemini 3 Flash' },
    { id: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  ],
  antigravity: [{ id: 'antigravity-default', label: 'Antigravity (Gemini 3.5 Flash 기반)' }],
}

export function ServiceIcon({ icon }: { icon: string | null }) {
  if (!icon) return <Rocket size={16} className="shrink-0 text-muted" />
  return (
    <span
      aria-hidden
      className="h-4 w-4 shrink-0 bg-current text-muted"
      style={{
        maskImage: `url(${icon})`,
        maskSize: 'contain',
        maskRepeat: 'no-repeat',
        maskPosition: 'center',
        WebkitMaskImage: `url(${icon})`,
        WebkitMaskSize: 'contain',
        WebkitMaskRepeat: 'no-repeat',
        WebkitMaskPosition: 'center',
      }}
    />
  )
}

export function ModelPickerPanel({
  view,
  highlightIndex,
  selected,
  onHighlightChange,
  onSelectService,
  onSelectModel,
  onBack,
}: {
  view: ModelView
  highlightIndex: number
  selected: SelectedModel
  onHighlightChange: (index: number) => void
  onSelectService: (id: ServiceId) => void
  onSelectModel: (modelId: string) => void
  onBack: () => void
}) {
  if (view === 'services') {
    return (
      <div className="overflow-hidden rounded-xl border border-hairline bg-surface text-left">
        <p className="border-b border-hairline px-4 py-2 text-xs text-muted">답변에 사용할 서비스</p>
        {SERVICES.map((s, i) => (
          <button
            key={s.id}
            type="button"
            onMouseEnter={() => onHighlightChange(i)}
            onClick={() => onSelectService(s.id)}
            className={`flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition-colors ${
              i === highlightIndex ? 'bg-foreground/8' : ''
            }`}
          >
            <ServiceIcon icon={s.icon} />
            <span className="flex-1 text-foreground">{s.label}</span>
            {selected.service === s.id && <Check size={14} className="shrink-0 text-accent-blue" />}
            <ChevronRight size={14} className="shrink-0 text-muted" />
          </button>
        ))}
      </div>
    )
  }

  const service = SERVICES.find((s) => s.id === view)!
  const models = MODELS_BY_SERVICE[view]

  return (
    <div className="overflow-hidden rounded-xl border border-hairline bg-surface text-left">
      <button
        type="button"
        onClick={onBack}
        className="flex w-full items-center gap-2 border-b border-hairline px-4 py-2 text-left text-xs text-muted transition-colors hover:text-foreground"
      >
        <ChevronLeft size={14} />
        {service.label}
      </button>
      {models.map((m, i) => (
        <button
          key={m.id}
          type="button"
          onMouseEnter={() => onHighlightChange(i)}
          onClick={() => onSelectModel(m.id)}
          className={`flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left text-sm transition-colors ${
            i === highlightIndex ? 'bg-foreground/8' : ''
          }`}
        >
          <span className="text-foreground">{m.label}</span>
          {selected.service === view && selected.modelId === m.id && (
            <Check size={14} className="shrink-0 text-accent-blue" />
          )}
        </button>
      ))}
    </div>
  )
}
