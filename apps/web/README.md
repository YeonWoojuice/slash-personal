# Slash

자연어 질문과 `/` 슬래시 명령어를 한 입력창에서 함께 쓰는 AI 에이전트 프론트엔드입니다. `/`는 이 프로덕트의 이름이자 로고이자 명령어 트리거예요 — 평범한 문장을 입력하면 로컬 LLM으로, `/`로 시작하면 파일 검색·웹 검색·AI 모델 선택 같은 명시적 명령으로 이어집니다.

## 기술 스택

- [Vite](https://vite.dev/) + React 19 + TypeScript
- [Tailwind CSS v4](https://tailwindcss.com/) (`@tailwindcss/vite`)
- React Router (해시 기반 다이얼로그 라우팅: 설정/명령어 가이드/단축키)
- `lucide-react` 아이콘

Next.js/CRA가 아니라 Vite 기반 정적 SPA이며, 최종 배포는 S3/CloudFront 같은 정적 호스팅을 목표로 합니다 (백엔드 서버 없음).

## 시작하기

### 로컬에서 바로 실행

```bash
npm install
npm run dev       # http://localhost:5173
```

```bash
npm run build     # 타입체크 + 프로덕션 빌드 (dist/)
npm run preview   # 빌드 결과 미리보기
```

### Docker Compose로 실행

```bash
docker compose up
```

`http://localhost:5173`에서 접속하면 됩니다. 소스 코드가 볼륨으로 마운트되어 있어서 코드를 수정하면 바로 반영돼요 (`node_modules`는 컨테이너 전용 볼륨으로 분리되어 있어 호스트 OS와 충돌하지 않습니다).

## 주요 기능

### 검색창 (두 가지 모드, 한 입력창)

- **자연어 모드**: 그냥 질문을 입력하면 로컬 LLM으로 전달돼요 (플레이스홀더 헬퍼 텍스트로 안내).
- **명령어 모드**: `/`로 시작하면 자동완성 트리가 뜨고, 명령 실행으로 취급돼요 (입력창의 `/` 배지와 제출 버튼이 파란색으로 바뀝니다).
- IME(한글/일본어/중국어) 조합 중 Enter 오작동 방지, 음성 입력(Web Speech API, 길게 눌러 녹음 / 클릭 토글), 파일·스크린샷 첨부를 지원합니다.

### 슬래시 명령어 트리 (`src/lib/commandTree.ts`)

- `/파일/검색` — 로컬 폴더 파일 검색 (아래 참고)
- `/파일/휴지통` — 삭제한 파일 복원 · 완전 삭제
- `/모델`, `/모델/검색 <질문>` — 답변에 쓸 AI 서비스·모델 선택 (Claude/ChatGPT/Gemini/Antigravity, 2단계 피커)
- `/검색/네이버`, `/검색/구글` — 웹 검색
- `/날씨/네이버`, `/지도/네이버`, `/길찾기/네이버` — 네이버 날씨·지도·길찾기

사이드바의 **명령어 가이드**에서 전체 트리와 단축키를 확인할 수 있고, 홈 화면의 예시 칩(`src/lib/exampleCommands.ts`)을 클릭하면 해당 명령어가 입력창에 바로 채워집니다.

### 로컬 파일 검색 (`/파일/검색`)

브라우저의 File System Access API(Chrome/Edge 전용)로 사용자가 명시적으로 그랑트한 폴더만 검색·삭제합니다.

- **여러 폴더 동시 검색**: 폴더를 계속 추가해서 한 번에 검색할 수 있어요.
- **재연결**: 그랑트한 폴더 핸들을 IndexedDB에 기억해뒀다가, 새로고침 후에도 버튼 한 번으로 재연결돼요 (매번 새로 고르지 않아도 됨).
- **읽기 전용 최상위 폴더 검색**: 홈/바탕화면/다운로드 같은 최상위 폴더는 브라우저가 그랑트를 막는데(Chrome 자체 보안 정책), `<input webkitdirectory>`를 이용한 읽기 전용 스냅샷 검색으로 이 폴더들도 검색만은 가능하게 했어요 (삭제 불가, 새로고침 시 재선택 필요).
- **휴지통**: 삭제는 실제로 각 폴더 안의 `.slash-trash` 서브폴더로 이동하는 것이며(OS 휴지통이 아님), `.manifest.json`에 메타데이터를 저장해서 새로고침 후에도 복원 가능하게 유지돼요.
- **시스템 파일 필터링**: `.DS_Store`, `Thumbs.db` 등 OS가 자동 생성하는 파일은 인덱싱에서 제외되고, 실제로 걸러진 파일명을 안내해줘요.
- **파일 열기**: 검색 결과를 클릭하면 새 탭에서 열립니다.

> **알려진 한계**: 브라우저 샌드박스 때문에 홈/바탕화면/문서/다운로드 폴더 "자체"는 읽기·쓰기 그랑트가 불가능하고(Chrome이 강제하는 정책, 코드로 우회 불가), Firefox/Safari는 이 기능 자체를 지원하지 않아요. 이 한계를 완전히 없애려면 Electron/Tauri 데스크톱 전환이 필요합니다 (로드맵상 이후 단계).

### 브라우저 요약 (`/요약`, WebLLM)

WebGPU를 지원하는 브라우저는 `/요약 <긴 글>`을 서버로 보내지 않고 이 브라우저
안에서 직접 요약합니다([`@mlc-ai/web-llm`](https://github.com/mlc-ai/web-llm) +
Qwen2.5-1.5B-Instruct, 4bit 양자화).

- **원문이 브라우저 밖으로 나가지 않습니다.** 모델 다운로드(최초 1회, 약 830MB,
  브라우저 캐시)·추론 전부 이 탭 안에서 끝나고, 서버에는 요약 **결과**만
  제출해 작업 이력에 남깁니다(원문·본문 자체는 전송 안 함).
- 별도 설치가 필요 없습니다 — WebGPU 지원 브라우저면 자동으로 동작하고, 무거운
  라이브러리(`src/lib/webllm.ts`)는 `/요약`을 실제로 쓰는 순간에만 동적으로
  불러와서(코드 스플리팅) 이 기능을 안 쓰는 사용자의 번들 크기에는 영향이
  없습니다.
- WebGPU를 지원하지 않는 브라우저는 안내 문구를 보여주고 기존 서버 경로(CPU
  추출 요약 또는 지정 PC의 로컬 어댑터)로 그대로 넘어갑니다 — 새로 생긴 대체
  동작이 아니라 원래도 서버로 가던 경로입니다.

> **알려진 한계**: `isWebGpuSupported()`는 `navigator.gpu` 존재 여부만 확인합니다
> — API 자체는 있지만 실제 GPU 어댑터를 못 구하는 환경(헤드리스, 오래된 GPU
> 등)은 이 사전 확인을 통과하고 실제 추론 단계에서 실패해, "미지원 안내" 대신
> 일반 실패 메시지로 보일 수 있습니다.

### 사이드바 & 설정

- 접기/펼치기 가능한 사이드바, 새 검색·히스토리·대시보드·즐겨찾기·파일 내비게이션, 최근 검색 목록(슬래시 명령어는 파란 배지로 구분 표시).
- 프로필 클릭 → 드롭다운 메뉴(설정/언어/도움말/요금제/자세히 알아보기 서브메뉴 → 단축키 다이얼로그 등).
- 설정은 별도 페이지가 아니라 모달 다이얼로그이며, 테마(시스템/라이트/다크) 전환이 여기서 이루어집니다.

## 디자인 시스템

`DESIGN.md`가 이 프로젝트의 브랜드/UI 스펙 원본입니다 (컬러, 타이포, 컴포넌트, 카피 톤 등). UI 작업 전에 꼭 참고해주세요. 취향/교정 기록은 `.omd/preferences.md`에 쌓입니다.

## 프로젝트 구조

```
src/
  components/   # SearchBar, Sidebar, AppShell, 각종 Dialog/Popover
  hooks/        # useLocalFileSearch, useTheme
  lib/          # commandTree, mockCommands, exampleCommands, folderHandleStore, user
  pages/        # HomePage
  types/        # File System Access / Web Speech API 타입 보강
```

## 관련 저장소

| 저장소 | 역할 |
|---|---|
| **slash-web** (현재) | 웹 클라이언트 — React·Vite UI, S3/CloudFront 배포 |
| [slash-api](https://github.com/LikeLionTeam4/slash-api) | 코어 API — 인증, 작업 관리, 실행 위치 결정, DB 연동 |
| [slash-nlu](https://github.com/LikeLionTeam4/slash-nlu) | 자연어 분석 — slash 명령 파싱, 규칙·Kiwi 의도 분류, 인자 추출 |
| [slash-llm](https://github.com/LikeLionTeam4/slash-llm) | LLM 서비스 — Gemma 추론, 요약·대화 생성 |
| [slash-runner](https://github.com/LikeLionTeam4/slash-runner) | PC 작업 실행기 — PC 파일 검색, 상태 조회, 로컬 AI 실행·결과 전달 |
| [slash-infra](https://github.com/LikeLionTeam4/slash-infra) | 인프라 — Terraform(AWS), Helm·ArgoCD 배포 |
| [slash-docs](https://github.com/LikeLionTeam4/slash-docs) | 프로젝트 문서 — 아키텍처, API 계약, ERD, 회의록 |
