import { type ReactNode } from 'react'
import { Settings, Keyboard, LogOut } from 'lucide-react'

function KeyCombo({ keys }: { keys: string[] }) {
  return (
    <span className="flex shrink-0 gap-1">
      {keys.map((k) => (
        <span
          key={k}
          className="flex h-5 min-w-[20px] items-center justify-center rounded-[6px] bg-foreground/8 px-1 font-mono text-2xs text-muted"
        >
          {k}
        </span>
      ))}
    </span>
  )
}

function MenuItem({
  icon: Icon,
  label,
  trailing,
  onClick,
}: {
  icon: typeof Settings
  label: string
  trailing?: ReactNode
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-foreground/8"
    >
      <Icon size={16} className="shrink-0 text-muted" />
      <span className="flex-1">{label}</span>
      {trailing}
    </button>
  )
}

export function ProfileMenu({
  email,
  onOpenSettings,
  onOpenShortcuts,
  onLogout,
  onClose,
}: {
  email: string
  onOpenSettings: () => void
  onOpenShortcuts: () => void
  onLogout: () => void
  onClose: () => void
}) {
  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div className="absolute bottom-full left-0 z-50 mb-2 w-[280px] overflow-hidden rounded-xl border border-hairline bg-surface-raised py-1 text-left shadow-2xl">
        <p className="truncate px-3 py-2 text-sm text-muted">{email}</p>

        <div className="border-t border-hairline py-1">
          <MenuItem
            icon={Settings}
            label="설정"
            trailing={<KeyCombo keys={['⌘', ',']} />}
            onClick={() => {
              onOpenSettings()
              onClose()
            }}
          />
          <MenuItem
            icon={Keyboard}
            label="단축키"
            trailing={<KeyCombo keys={['⌘', '/']} />}
            onClick={() => {
              onOpenShortcuts()
              onClose()
            }}
          />
        </div>

        <div className="border-t border-hairline pt-1">
          <MenuItem
            icon={LogOut}
            label="로그아웃"
            onClick={() => {
              onClose()
              onLogout()
            }}
          />
        </div>
      </div>
    </>
  )
}
