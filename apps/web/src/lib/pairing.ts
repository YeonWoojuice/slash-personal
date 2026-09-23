// PC 등록(페어링) — frontend-api-contract.md "PC 등록 화면(W1-02)" 구현.
// 발급은 사용자 인증(Bearer)이 필요하지만, Agent가 부르는 /agent/pair·/pair/verify는 여기서
// 다루지 않는다 — 그건 사용자 인증 없이 Ed25519로 동작하는 별도 경로다.
import { apiRequest } from './apiClient'

export interface PairingRequest {
  pairingRequestId: string
  pairingCode: string
  expiresAt: string
}

export type PairingStatus =
  | { status: 'PENDING'; deviceId: null }
  | { status: 'CLAIMED'; deviceId: string }

export function createPairingRequest(): Promise<PairingRequest> {
  return apiRequest<PairingRequest>('/api/v1/pairing-requests', { method: 'POST' })
}

export function getPairingStatus(pairingRequestId: string): Promise<PairingStatus> {
  return apiRequest<PairingStatus>(`/api/v1/pairing-requests/${pairingRequestId}`)
}
