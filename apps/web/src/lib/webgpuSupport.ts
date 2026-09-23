// webllm.ts와 분리한 이유 하나뿐이다 — webllm.ts는 @mlc-ai/web-llm(수 MB)을 정적으로 import
// 해서, SearchBar.tsx가 이 지원 여부 확인 하나만 하려 해도 그 무거운 라이브러리 전체가
// 메인 번들에 딸려 들어온다(실측: 6.4MB). 이 파일은 그 의존성이 전혀 없어, /요약을 한 번도
// 안 쓰는 사용자는 이 몇 줄 말고는 아무것도 안 받는다. 실제 요약 실행은 SearchBar.tsx가
// `await import('./webllm')`로 그 순간에만 받는다.
export function isWebGpuSupported(): boolean {
  return typeof navigator !== 'undefined' && 'gpu' in navigator
}
