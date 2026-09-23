#!/usr/bin/env python3
"""Start slash-nlu/llm and run a small HTTP contract smoke test."""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, TextIO

import httpx


LLM_ROOT = Path(__file__).resolve().parents[1]
NLU_ROOT = LLM_ROOT.parent / "slash-nlu"


class DemoError(RuntimeError):
    pass


def python_for(repo: Path) -> Path:
    candidate = repo / ".venv" / "bin" / "python"
    if not candidate.is_file():
        raise DemoError(
            f"{repo.name}/.venv가 없습니다. README의 설치 명령을 먼저 실행해 주세요."
        )
    return candidate


def start_service(
    name: str,
    repo: Path,
    python: Path,
    app: str,
    port: int,
    log: TextIO,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.Popen:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    try:
        return subprocess.Popen(
            [
                str(python),
                "-m",
                "uvicorn",
                app,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=str(repo),
            env=process_env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        raise DemoError(f"{name} 실행에 실패했습니다: {exc}") from exc


def wait_ready(name: str, url: str, process: subprocess.Popen, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise DemoError(f"{name}가 준비되기 전에 종료되었습니다.")
        try:
            response = httpx.get(url, timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise DemoError(f"{name} 준비 시간이 {timeout:.0f}초를 초과했습니다: {url}")


def post_json(client: httpx.Client, url: str, payload: dict) -> dict:
    response = client.post(url, json=payload)
    if response.status_code != 200:
        raise DemoError(f"POST {url} -> {response.status_code}: {response.text}")
    return response.json()


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise DemoError(message)


def run_scenarios(nlu_url: str, llm_url: str) -> None:
    with httpx.Client(timeout=10) as client:
        file_result = post_json(
            client,
            f"{nlu_url}/internal/v1/nlu/analyze",
            {"requestId": "demo-file", "text": "회의록 파일 찾아줘"},
        )
        expect(file_result["decision"] == "TASK", "파일 검색 decision이 TASK가 아닙니다.")
        expect(file_result["taskType"] == "FILE_SEARCH", "파일 검색 taskType이 다릅니다.")
        expect(file_result["parameters"].get("query") == "회의록", "파일 검색 query가 다릅니다.")
        expect("searchFolderId" not in file_result["parameters"], "NLU가 searchFolderId를 만들었습니다.")
        expect("processingRoute" not in file_result, "NLU가 processingRoute를 반환했습니다.")
        print("✓ 자연어 파일 검색 계약")

        status_result = post_json(
            client,
            f"{nlu_url}/internal/v1/nlu/analyze",
            {"requestId": "demo-status", "command": {"path": ["status"], "operands": []}},
        )
        expect(status_result["taskType"] == "SYSTEM_STATUS", "상태 조회 taskType이 다릅니다.")
        expect(status_result["decision"] == "TASK", "상태 조회 decision이 TASK가 아닙니다.")
        print("✓ slash 상태 조회 계약")

        weather_result = post_json(
            client,
            f"{nlu_url}/internal/v1/nlu/analyze",
            {"requestId": "demo-weather", "command": {"path": ["weather"], "operands": []}},
        )
        expect(weather_result["decision"] == "CLARIFY", "날씨 위치 누락이 CLARIFY가 아닙니다.")
        expect(weather_result["missingRequiredParameters"] == ["location"], "날씨 누락 필드가 다릅니다.")
        print("✓ 필수 인자 누락 확인 계약")

        source = "팀 연동 테스트를 위한 충분히 긴 원문입니다. " * 8
        nlu_summary = post_json(
            client,
            f"{nlu_url}/internal/v1/nlu/analyze",
            {"requestId": "demo-summary", "command": {"path": ["summary"], "operands": [source]}},
        )
        expect(nlu_summary["decision"] == "TASK", "긴 요약 입력이 TASK가 아닙니다.")
        expect(nlu_summary["taskType"] == "TEXT_SUMMARY", "요약 taskType이 다릅니다.")
        llm_summary = post_json(
            client,
            f"{llm_url}/internal/v1/llm/summary",
            {
                "text": nlu_summary["parameters"]["text"],
                "requestId": nlu_summary["requestId"],
                "taskId": "demo-task-1",
            },
        )
        expect(bool(llm_summary.get("summary")), "LLM 요약 결과가 비었습니다.")
        expect(llm_summary.get("requestId") == "demo-summary", "requestId가 보존되지 않았습니다.")
        expect(llm_summary.get("taskId") == "demo-task-1", "taskId가 보존되지 않았습니다.")
        print("✓ NLU → LLM 요약 및 추적 ID 계약")

        unsupported = post_json(
            client,
            f"{nlu_url}/internal/v1/nlu/analyze",
            {"requestId": "demo-command", "command": {"path": ["command"], "operands": ["hello"]}},
        )
        expect(unsupported["decision"] == "UNSUPPORTED", "비 MVP command가 UNSUPPORTED가 아닙니다.")
        expect(unsupported["taskType"] is None, "UNSUPPORTED taskType은 null이어야 합니다.")
        print("✓ 비 MVP command 차단 계약")


def stop_all(processes: List[subprocess.Popen]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 5
    for process in reversed(processes):
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-ollama", action="store_true", help="가짜 Ollama 대신 OLLAMA_URL의 실제 서버 사용")
    parser.add_argument("--nlu-port", type=int, default=18001)
    parser.add_argument("--llm-port", type=int, default=18002)
    parser.add_argument("--mock-ollama-port", type=int, default=11435)
    args = parser.parse_args()

    processes: List[subprocess.Popen] = []
    log_path: Optional[Path] = None
    try:
        if not (NLU_ROOT / "main.py").is_file():
            raise DemoError(f"sibling 저장소를 찾을 수 없습니다: {NLU_ROOT}")
        nlu_python = python_for(NLU_ROOT)
        llm_python = python_for(LLM_ROOT)
        with tempfile.NamedTemporaryFile(prefix="slash-team-demo-", suffix=".log", delete=False, mode="w+") as log:
            log_path = Path(log.name)
            if args.real_ollama:
                ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
                try:
                    response = httpx.get(f"{ollama_url}/api/tags", timeout=2)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise DemoError(f"실제 Ollama에 연결할 수 없습니다: {ollama_url}") from exc
            else:
                ollama_url = f"http://127.0.0.1:{args.mock_ollama_port}"
                mock = start_service("가짜 Ollama", LLM_ROOT, llm_python, "scripts.mock_ollama:app", args.mock_ollama_port, log)
                processes.append(mock)
                wait_ready("가짜 Ollama", f"{ollama_url}/api/tags", mock)

            nlu = start_service("NLU", NLU_ROOT, nlu_python, "main:app", args.nlu_port, log)
            processes.append(nlu)
            llm = start_service(
                "LLM",
                LLM_ROOT,
                llm_python,
                "main:app",
                args.llm_port,
                log,
                env={"OLLAMA_URL": ollama_url, "LLM_TIMEOUT": "10"},
            )
            processes.append(llm)
            nlu_url = f"http://127.0.0.1:{args.nlu_port}"
            llm_url = f"http://127.0.0.1:{args.llm_port}"
            wait_ready("NLU", f"{nlu_url}/health", nlu)
            wait_ready("LLM", f"{llm_url}/health", llm)
            run_scenarios(nlu_url, llm_url)
        print("\n팀 스모크 테스트 5/5 통과")
        if log_path:
            log_path.unlink(missing_ok=True)
        return 0
    except (DemoError, KeyError, TypeError) as exc:
        print(f"\n실패: {exc}", file=sys.stderr)
        if log_path and log_path.is_file():
            print(f"서비스 로그: {log_path}", file=sys.stderr)
        return 1
    finally:
        stop_all(processes)


if __name__ == "__main__":
    raise SystemExit(main())
