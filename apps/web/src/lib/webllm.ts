// 브라우저 안에서 도는 요약 — slash-docs#3 권장 순서 6번(WebLLM 경로).
//
// 이 파일은 브라우저 밖으로 원문을 보내지 않는다. 모델 다운로드·추론 전부 이 탭 안에서
// 끝난다 — slash-api에는 결과와 메타데이터만 실어 보낸다(SearchBar.tsx 쪽 책임).
//
// 모델은 Qwen2.5-1.5B-Instruct(4bit 양자화)로 고정한다 — WebLLM 사전빌드 목록 중 요약·분류에
// 적합하다고 알려져 있고, VRAM 요구량이 약 1.6GB로 작아 처음 받을 때 부담이 적다(README
// 조사, 2026-08-21). 모델을 바꾸려면 이 파일의 MODEL_ID 하나만 고치면 된다 — 나머지 코드는
// 모델에 의존하지 않는다.
import { CreateMLCEngine, type MLCEngine, type InitProgressReport } from '@mlc-ai/web-llm'

import {
  generateValidatedWebLlmSummary,
  WEBLLM_MODEL_ID,
  WEBLLM_PROMPT_VERSION,
} from './webllmSummary'

// WebGPU 지원 여부만 확인할 때는 이 파일이 아니라 webgpuSupport.ts를 쓴다 — 그쪽은
// @mlc-ai/web-llm을 안 끌어와서 번들이 안 커진다. 이 파일은 실제로 요약을 실행할 때만
// SearchBar.tsx가 동적 import로 불러온다.
export { isWebGpuSupported } from './webgpuSupport'

export const MODEL_ID = WEBLLM_MODEL_ID

// 고정 시스템 프롬프트가 바뀌면 이 값을 올린다 — slash-docs#3 처리 원칙 2번(작업 이력에
// "무엇으로 만든 결과인지" 남기기)이 요구하는 값이라, GENERATION_CONFIG처럼 프롬프트도
// 버전으로 추적한다.
export const PROMPT_VERSION = WEBLLM_PROMPT_VERSION

// slash-docs#3 원칙 — "WebLLM은 대화 기억이 없는 단건 생성기로 사용한다": 매 요청 고정
// 시스템 프롬프트 + 현재 입력만 쓰고, 이전 요청을 다음 요청에 넘기지 않는다. 편차를 줄이려고
// temperature 0·top_p 1·고정 seed를 쓴다 — 그렇다고 기기마다 결과가 완전히 같아야 하는
// 것은 아니다(WebGPU 구현·부동소수점 차이는 남는다).
const GENERATION_CONFIG = {
  temperature: 0,
  top_p: 1,
  seed: 0,
  max_tokens: 256,
} as const

let enginePromise: Promise<MLCEngine> | null = null

/** 엔진을 한 번만 만들어 재사용한다 — 매 요약마다 모델을 다시 받으면 안 된다.
 * 로딩 중 진행률은 onProgress로 받는다(최초 1회만 의미 있음, 이후 호출은 캐시된 엔진을
 * 즉시 반환하므로 onProgress가 아예 안 불릴 수 있다). */
async function getEngine(onProgress?: (report: InitProgressReport) => void): Promise<MLCEngine> {
  if (!enginePromise) {
    enginePromise = CreateMLCEngine(MODEL_ID, {
      initProgressCallback: onProgress,
    }).catch((e) => {
      // 실패한 시도를 캐시해 두면 재시도할 방법이 없어진다 — 다음 호출이 다시 시도하게 한다.
      enginePromise = null
      throw e
    })
  }
  return enginePromise
}

export type SummarizeProgress = { phase: 'loading'; report: InitProgressReport } | { phase: 'generating' }

/** 브라우저 안에서 텍스트를 요약한다. 원문은 이 함수 밖으로(네트워크로) 나가지 않는다. */
export async function summarizeInBrowser(
  text: string,
  onProgress?: (progress: SummarizeProgress) => void,
): Promise<string> {
  return generateValidatedWebLlmSummary(text, async (messages) => {
    const engine = await getEngine((report) => onProgress?.({ phase: 'loading', report }))
    onProgress?.({ phase: 'generating' })

    const response = await engine.chat.completions.create({
      messages,
      ...GENERATION_CONFIG,
    })
    return response.choices[0]?.message?.content
  })
}
