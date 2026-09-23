import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { checkAgentStatus } from '../lib/agentStatus'

export type AgentStatus = 'online' | 'offline'

// slash-api의 status는 최대 2분까지 늦을 수 있다(하트비트 90초 무응답 판정을 30초마다 확인 —
// frontend-api-contract.md). 5초 폴링은 그 지연에 비해 과했던 값이라 늘렸다.
const POLL_INTERVAL_MS = 30000

const AgentStatusContext = createContext<AgentStatus | null>(null)

/**
 * 등록된 PC 중 하나라도 연결돼 있는지를 앱 전체가 하나의 값으로 공유한다 — 사이드바 아이콘과
 * 검색창 경고, 설정의 PC 관리가 서로 다른 순간에 서로 다른 상태를 보여주면 안 되므로 폴링도
 * 한 번만 돈다. slash-api가 GET /api/v1/devices로 이미 아는 값을 그대로 받아쓴다.
 */
export function AgentStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AgentStatus>('offline')

  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      const online = await checkAgentStatus()
      if (!cancelled) setStatus(online ? 'online' : 'offline')
    }

    poll()
    const id = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  return <AgentStatusContext.Provider value={status}>{children}</AgentStatusContext.Provider>
}

export function useAgentStatus(): AgentStatus {
  const value = useContext(AgentStatusContext)
  if (value === null) throw new Error('useAgentStatus는 AgentStatusProvider 안에서만 쓸 수 있어요.')
  return value
}
