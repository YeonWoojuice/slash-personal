// 로그인한 사용자 정보 — frontend-api-contract.md "GET /api/v1/me" (동작 중).
import { apiRequest } from './apiClient'

export interface MeResponse {
  userId: string
  email: string
  /** 계약서 §2: null 필드는 응답에서 빠진다 — Cognito 토큰에 name/given_name 클레임이
   *  없으면 아예 안 온다. */
  displayName?: string
  timezone: string
  status: string
  createdAt: string
}

export function getMe(): Promise<MeResponse> {
  return apiRequest<MeResponse>('/api/v1/me')
}
