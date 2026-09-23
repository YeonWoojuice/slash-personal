/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_COGNITO_REGION: string
  readonly VITE_COGNITO_USER_POOL_ID: string
  readonly VITE_COGNITO_CLIENT_ID: string
  /** 로그아웃 전용 — Cognito 고유 로그아웃 방식(client_id+logout_uri)에 쓴다. lib/oidc.ts 참고. */
  readonly VITE_COGNITO_DOMAIN: string
  /** frontend-api-contract.md §9 TBD — 백엔드/인프라가 dev API 주소를 확정하면 채운다. */
  readonly VITE_API_BASE_URL: string
  /** MS Clarity 프로젝트 ID. 비어있거나 dev 빌드면 초기화하지 않는다. lib/clarity.ts 참고. */
  readonly VITE_CLARITY_PROJECT_ID?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
