import { useEffect, useRef, useState } from 'react'
import { Mic, Check } from 'lucide-react'

type Device = { deviceId: string; label: string }

export function MicSettingsPopover({
  selectedDeviceId,
  onSelectDevice,
  holdToRecord,
  onHoldToRecordChange,
  onClose,
}: {
  selectedDeviceId: string | null
  onSelectDevice: (id: string) => void
  holdToRecord: boolean
  onHoldToRecordChange: (value: boolean) => void
  onClose: () => void
}) {
  const [devices, setDevices] = useState<Device[]>([])
  const [level, setLevel] = useState(0)
  const rafRef = useRef<number | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const streamRef = useRef<MediaStream | null>(null)

  useEffect(() => {
    let cancelled = false

    async function setup() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: selectedDeviceId ? { deviceId: { exact: selectedDeviceId } } : true,
        })
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop())
          return
        }
        streamRef.current = stream

        const list = await navigator.mediaDevices.enumerateDevices()
        setDevices(
          list
            .filter((d) => d.kind === 'audioinput')
            .map((d) => ({ deviceId: d.deviceId, label: d.label || '마이크' })),
        )

        const ctx = new AudioContext()
        audioCtxRef.current = ctx
        const source = ctx.createMediaStreamSource(stream)
        const analyser = ctx.createAnalyser()
        analyser.fftSize = 256
        source.connect(analyser)
        const data = new Uint8Array(analyser.frequencyBinCount)

        const tick = () => {
          analyser.getByteTimeDomainData(data)
          let sumSquares = 0
          for (const sample of data) {
            const centered = sample - 128
            sumSquares += centered * centered
          }
          const rms = Math.sqrt(sumSquares / data.length) / 128
          setLevel(Math.min(1, rms * 4))
          rafRef.current = requestAnimationFrame(tick)
        }
        tick()
      } catch {
        // mic permission denied or unavailable — device list stays empty
      }
    }

    setup()

    return () => {
      cancelled = true
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      streamRef.current?.getTracks().forEach((track) => track.stop())
      audioCtxRef.current?.close()
    }
  }, [selectedDeviceId])

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div className="absolute right-0 top-full z-50 mt-2 w-64 overflow-hidden rounded-xl border border-hairline bg-surface-raised py-2 text-left shadow-2xl">
        <div className="flex items-center gap-2 px-3 pb-2">
          <Mic size={14} className="shrink-0 text-muted" />
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-foreground/10">
            <div
              className="h-full rounded-full bg-accent-blue transition-[width] duration-75"
              style={{ width: `${Math.round(level * 100)}%` }}
            />
          </div>
        </div>
        <div className="my-1 border-t border-hairline" />
        {devices.length === 0 ? (
          <p className="px-3 py-2 text-xs text-muted">마이크 권한이 필요해요.</p>
        ) : (
          devices.map((d) => (
            <button
              key={d.deviceId}
              type="button"
              onClick={() => onSelectDevice(d.deviceId)}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-foreground/8"
            >
              <span className="flex-1 truncate">{d.label}</span>
              {(selectedDeviceId ?? devices[0]?.deviceId) === d.deviceId && (
                <Check size={14} className="shrink-0 text-accent-blue" />
              )}
            </button>
          ))
        )}
        <div className="my-1 border-t border-hairline" />
        <div className="flex items-center gap-2.5 px-3 py-2">
          <Mic size={14} className="shrink-0 text-muted" />
          <span className="flex-1 text-sm text-foreground">길게 눌러 녹음</span>
          <button
            type="button"
            role="switch"
            aria-checked={holdToRecord}
            onClick={() => onHoldToRecordChange(!holdToRecord)}
            className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
              holdToRecord ? 'bg-accent-blue' : 'bg-foreground/20'
            }`}
          >
            <span
              className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                holdToRecord ? 'translate-x-4' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
      </div>
    </>
  )
}
