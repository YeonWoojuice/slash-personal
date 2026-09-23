// 로컬 에이전트가 응답하는지는 브라우저가 직접 확인할 방법이 없다 — slash-agent(slash-pc-runner)는
// slash-api와 자기만의 WSS(/ws/agent)로만 붙고, 브라우저를 향한 로컬 포트는 열지 않는다
// (slash-agent README "메시지 프로토콜" 절). slash-api가 이미 하트비트로 알고 있는 값을
// GET /api/v1/devices의 status로 그대로 받아써야 한다 — frontend-api-contract.md
// "status로 연결 여부 판단하기": READY/ONLINE/BUSY만 연결됨으로 본다.
import { listDevices } from './devices'

export async function checkAgentStatus(): Promise<boolean> {
  try {
    // silent: true — 30초마다 도는 백그라운드 폴링이다. 세션이 만료돼 있어도 여기서
    // signinRedirect()로 로그인 화면으로 튕기면 안 된다(계속 반복되면 리다이렉트 루프가 된다).
    const { devices } = await listDevices({ silent: true })
    return devices.some((d) => d.status !== 'OFFLINE')
  } catch {
    return false
  }
}
