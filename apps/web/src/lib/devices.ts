// 등록된 PC 목록 — frontend-api-contract.md "지정 PC 관리 화면(W1-03)" 구현.
// 기기 이름 변경은 계약만 확정된 상태라(슬래시-api #22) 여기 없다.
import { apiRequest, type ApiRequestOptions } from './apiClient'

export type DeviceStatus = 'READY' | 'ONLINE' | 'BUSY' | 'OFFLINE'

export interface Device {
  deviceId: string
  name: string
  status: DeviceStatus
  os: 'WINDOWS' | 'MACOS'
  // Agent가 보고한 원문 그대로 — 한 번도 연결된 적 없으면 없다.
  osVersion?: string
  agentVersion?: string
  lastSeenAt?: string
  registeredAt: string
  // 해제(DELETE) 요청의 If-Match에 그대로 넣는다 — 다른 탭에서 먼저 바뀐 기기를 낡은 화면이
  // 덮어쓰지 않도록 서버가 요구하는 낙관적 잠금 값이다(slash-api DeviceResponse.version).
  version: number
  // 새 작업 수신 여부. 연결 해제(REVOKED)와 달리 되돌릴 수 있다 — 연결은 유지한 채 작업만
  // 안 받는다(slash-api #24).
  acceptingTasks: boolean
}

interface DeviceListResponse {
  devices: Device[]
}

export function listDevices(options?: Pick<ApiRequestOptions, 'silent'>): Promise<DeviceListResponse> {
  return apiRequest<DeviceListResponse>('/api/v1/devices', options)
}

/** PC 등록 해제. 되돌릴 수 없다 — 붙어있는 연결도 서버가 그 자리에서 끊는다(slash-api #23). */
export function revokeDevice(deviceId: string, expectedVersion: number): Promise<void> {
  return apiRequest<void>(`/api/v1/devices/${deviceId}`, {
    method: 'DELETE',
    ifMatch: `"${expectedVersion}"`,
  })
}

/**
 * 새 작업 수신을 켜고 끈다(slash-api #24). 연결은 유지한 채 작업 전달만 멈춘다 — 해제와 달리
 * 되돌릴 수 있다. 토글이 아니라 원하는 상태를 그대로 보낸다(같은 값을 두 번 보내도 결과가 같음).
 * 바뀐 기기 전체(새 version 포함)가 돌아오므로 목록을 다시 조회하지 않아도 된다.
 */
export function setTaskIntake(deviceId: string, accepting: boolean, expectedVersion: number): Promise<Device> {
  return apiRequest<Device>(`/api/v1/devices/${deviceId}/task-intake`, {
    method: 'PATCH',
    body: { accepting },
    ifMatch: `"${expectedVersion}"`,
  })
}
