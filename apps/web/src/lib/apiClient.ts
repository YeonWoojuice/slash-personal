// slash-api 공통 연동 규약(frontend-api-contract.md) 구현.
// 개별 엔드포인트가 아니라 모든 API에 적용되는 부분만 다룬다 — §1(헤더)~§4(에러 코드).
import { userManager } from './oidc'

const BASE_URL = import.meta.env.VITE_API_BASE_URL

// §4의 에러 코드 전체. switch/if에서 자동완성·오타 방지용 — 계약서에 새 코드가 추가되면 여기도 갱신한다.
export type ApiErrorCode =
  | 'AUTH_REQUIRED'
  | 'FORBIDDEN'
  | 'AGENT_AUTH_FAILED'
  | 'PAIRING_CODE_INVALID'
  | 'VALIDATION_ERROR'
  | 'INVALID_PARAMETERS'
  | 'RESOURCE_NOT_FOUND'
  | 'RESOURCE_VERSION_MISMATCH'
  | 'IDEMPOTENCY_CONFLICT'
  | 'DEVICE_NOT_READY'
  | 'DEVICE_BUSY'
  | 'TASK_TYPE_NOT_SUPPORTED'
  | 'TASK_EXPIRED'
  | 'UNRECOGNIZED_COMMAND'
  | 'SEARCH_FOLDER_NOT_FOUND'
  | 'FILE_NOT_FOUND'
  | 'WORKSPACE_NOT_FOUND'
  | 'CODE_AGENT_NOT_CONFIGURED'
  | 'POLICY_DENIED'
  | 'AGENT_REJECTED'
  | 'AGENT_TASK_FAILED'
  | 'BROWSER_TASK_FAILED'
  | 'DEVICE_REVOKED'
  | 'NLU_UNAVAILABLE'
  | 'LLM_NOT_READY'
  | 'UPSTREAM_UNAVAILABLE'
  | 'LOCATION_NOT_FOUND'
  | 'UNSUPPORTED_SCHEMA_VERSION'
  | 'INTERNAL_ERROR'

export class ApiError extends Error {
  code: ApiErrorCode | 'UNKNOWN_ERROR'
  details?: unknown
  requestId?: string

  constructor(code: ApiErrorCode | 'UNKNOWN_ERROR', message: string, details?: unknown, requestId?: string) {
    super(message)
    this.code = code
    this.details = details
    this.requestId = requestId
  }
}

interface SuccessEnvelope<T> {
  data: T
  meta: { requestId: string; serverTime: string }
}

interface ErrorEnvelope {
  error: { code: ApiErrorCode; message: string; details?: unknown }
  meta: { requestId: string; serverTime: string }
}

export interface ApiRequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  headers?: Record<string, string>
  /** 작업 생성(POST /api/v1/requests 등)용 — 재시도 시 같은 값을 유지해야 중복 방지가 된다. newIdempotencyKey()로 만든다. */
  idempotencyKey?: string
  /** 수정 요청용 — 직전 조회 응답의 ETag를 그대로 넣는다. */
  ifMatch?: string
  /** §6의 공개 경로(health, agent pair 등) 호출 시 — Authorization 헤더를 아예 안 붙인다. */
  skipAuth?: boolean
  /** 백그라운드 폴링용 — AUTH_REQUIRED를 받아도 signinSilent/signinRedirect로 이어가지 않고
   *  그냥 실패로 던진다. 세션이 잠깐 꼬였다고 사용자가 보고 있던 화면에서 로그인 페이지로
   *  강제 이동시키면 안 된다(그것도 30초마다 반복되면 리다이렉트 루프가 된다). */
  silent?: boolean
}

async function getAccessToken(): Promise<string | null> {
  const user = await userManager.getUser()
  if (!user || user.expired) return null
  // 계약서 §5: ID Token을 보내면 거부된다 — 반드시 Access Token.
  return user.access_token
}

/** UUID v4 — Idempotency-Key 헤더에 쓴다. 버튼 클릭 1회당 하나 만들어서 재시도까지 그대로 재사용한다. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}, _retried = false): Promise<T> {
  const { method = 'GET', body, headers = {}, idempotencyKey, ifMatch, skipAuth, silent } = options

  const reqHeaders: Record<string, string> = { ...headers }
  if (body !== undefined) reqHeaders['Content-Type'] = 'application/json; charset=utf-8'
  if (idempotencyKey) reqHeaders['Idempotency-Key'] = idempotencyKey
  if (ifMatch) reqHeaders['If-Match'] = ifMatch

  if (!skipAuth) {
    const token = await getAccessToken()
    if (token) reqHeaders['Authorization'] = `Bearer ${token}`
  }

  let res: Response
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: reqHeaders,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError('UPSTREAM_UNAVAILABLE', '네트워크 오류가 발생했습니다. 잠시 후 다시 시도해주세요.')
  }

  // 204 No Content(예: DELETE /api/v1/devices/{id})는 본문이 아예 없다 — res.json()이 빈
  // 문자열을 파싱하려다 실패해서 아래 error 분기로 잘못 떨어지는 것을 막는다.
  if (res.status === 204) {
    return undefined as T
  }

  const json = (await res.json().catch(() => null)) as SuccessEnvelope<T> | ErrorEnvelope | null

  if (res.ok && json && 'data' in json) {
    return json.data
  }

  const errCode = json && 'error' in json ? json.error.code : undefined
  const errMessage = json && 'error' in json ? json.error.message : '알 수 없는 오류가 발생했습니다.'
  const errDetails = json && 'error' in json ? json.error.details : undefined
  const requestId = json?.meta?.requestId

  // 계약서 §5: 갱신 → 원요청 1회만 재시도 → 또 실패하면 로그인 화면으로.
  if (errCode === 'AUTH_REQUIRED' && !skipAuth && !silent) {
    if (!_retried) {
      try {
        await userManager.signinSilent()
        return apiRequest<T>(path, options, true)
      } catch {
        // 갱신 자체가 실패 — 아래 signinRedirect로 이어진다.
      }
    }
    await userManager.signinRedirect()
    throw new ApiError('AUTH_REQUIRED', errMessage, errDetails, requestId)
  }

  throw new ApiError(errCode ?? 'UNKNOWN_ERROR', errMessage, errDetails, requestId)
}
