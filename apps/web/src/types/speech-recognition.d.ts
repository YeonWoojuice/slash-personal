export {}

declare global {
  interface SpeechRecognitionEventLike extends Event {
    results: ArrayLike<ArrayLike<{ transcript: string }>>
  }

  interface SpeechRecognitionInstance extends EventTarget {
    lang: string
    interimResults: boolean
    continuous: boolean
    onresult: ((event: SpeechRecognitionEventLike) => void) | null
    onerror: ((event: Event) => void) | null
    onend: (() => void) | null
    start(): void
    stop(): void
  }

  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionInstance
    webkitSpeechRecognition?: new () => SpeechRecognitionInstance
  }
}
