#!/usr/bin/env python3
"""Verify a deployed slash-llm instance and its configured Ollama model."""

import argparse
import math
import os
import sys
import time
from typing import Any, Dict, Optional

import httpx


DEFAULT_MODEL = "gemma3:4b"
DEFAULT_PROBE_TIMEOUT = 10.0
DEFAULT_SUMMARY_TIMEOUT = 180.0
REQUEST_ID = "dev-smoke-request"
TASK_ID = "dev-smoke-task"
SMOKE_TEXT = "배포된 LLM과 Ollama 연결을 확인하기 위한 합성 테스트 문장입니다. " * 8


class SmokeError(RuntimeError):
    pass


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("0보다 큰 숫자를 입력해 주세요.") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("0보다 큰 숫자를 입력해 주세요.")
    return parsed


def response_json(response: httpx.Response, path: str) -> Dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SmokeError(f"{path} 응답이 JSON 형식이 아닙니다.") from exc
    if not isinstance(payload, dict):
        raise SmokeError(f"{path} 응답이 JSON 객체가 아닙니다.")
    return payload


def failure_code(payload: Dict[str, Any]) -> Optional[str]:
    reason = payload.get("reason")
    if isinstance(reason, str):
        return reason
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return error["code"]
    return None


def require_ok(response: httpx.Response, path: str) -> Dict[str, Any]:
    payload = response_json(response, path)
    if response.status_code != 200:
        code = failure_code(payload)
        suffix = f" ({code})" if code else ""
        raise SmokeError(f"{path} -> HTTP {response.status_code}{suffix}")
    return payload


def run_smoke(
    base_url: str,
    *,
    expected_model: str = DEFAULT_MODEL,
    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,
    summary_timeout: float = DEFAULT_SUMMARY_TIMEOUT,
    transport: Optional[httpx.BaseTransport] = None,
) -> None:
    try:
        parsed_url = httpx.URL(base_url)
    except httpx.InvalidURL as exc:
        raise SmokeError("LLM 주소 형식이 올바르지 않습니다.") from exc
    if parsed_url.scheme not in ("http", "https") or not parsed_url.host:
        raise SmokeError("LLM 주소는 http 또는 https URL이어야 합니다.")
    if probe_timeout <= 0 or summary_timeout <= 0:
        raise SmokeError("timeout은 0보다 커야 합니다.")

    try:
        with httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=probe_timeout,
            transport=transport,
        ) as client:
            health = require_ok(client.get("/health"), "/health")
            if health.get("status") != "ok":
                raise SmokeError("/health 상태가 기대값과 다릅니다.")
            if health.get("model") != expected_model:
                raise SmokeError("/health 모델이 기대값과 다릅니다.")
            print("✓ /health")

            ready = require_ok(client.get("/ready"), "/ready")
            if ready.get("status") != "ready":
                raise SmokeError("/ready 상태가 기대값과 다릅니다.")
            if ready.get("model") != expected_model:
                raise SmokeError("/ready 모델이 기대값과 다릅니다.")
            print(f"✓ /ready ({expected_model})")

            started_at = time.monotonic()
            summary_response = client.post(
                "/internal/v1/llm/summary",
                json={
                    "text": SMOKE_TEXT,
                    "requestId": REQUEST_ID,
                    "taskId": TASK_ID,
                },
                timeout=summary_timeout,
            )
            elapsed = time.monotonic() - started_at
            summary = require_ok(
                summary_response,
                "/internal/v1/llm/summary",
            )
            if not isinstance(summary.get("summary"), str) or not summary["summary"].strip():
                raise SmokeError("요약 결과가 비어 있습니다.")
            if summary.get("model") != expected_model:
                raise SmokeError("요약 응답의 모델이 기대값과 다릅니다.")
            if summary.get("requestId") != REQUEST_ID or summary.get("taskId") != TASK_ID:
                raise SmokeError("요약 응답의 추적 ID가 요청과 다릅니다.")
            print(f"✓ /summary (model 및 추적 ID 확인, {elapsed:.2f}s)")
    except httpx.HTTPError as exc:
        raise SmokeError(f"LLM 서비스에 연결할 수 없습니다: {type(exc).__name__}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("LLM_SMOKE_BASE_URL"),
        help="배포된 slash-llm 주소 (기본: LLM_SMOKE_BASE_URL)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("LLM_SMOKE_MODEL", DEFAULT_MODEL),
        help="기대 모델명 (기본: LLM_SMOKE_MODEL 또는 gemma3:4b)",
    )
    parser.add_argument(
        "--probe-timeout",
        type=positive_float,
        default=os.getenv("LLM_SMOKE_PROBE_TIMEOUT", str(DEFAULT_PROBE_TIMEOUT)),
        help="health/readiness 요청 제한 시간(초)",
    )
    parser.add_argument(
        "--summary-timeout",
        type=positive_float,
        default=os.getenv("LLM_SMOKE_SUMMARY_TIMEOUT", str(DEFAULT_SUMMARY_TIMEOUT)),
        help="summary 요청 제한 시간(초)",
    )
    args = parser.parse_args()

    if not args.base_url:
        print("실패: LLM_SMOKE_BASE_URL 또는 --base-url을 지정해 주세요.", file=sys.stderr)
        return 2
    try:
        run_smoke(
            args.base_url,
            expected_model=args.model,
            probe_timeout=args.probe_timeout,
            summary_timeout=args.summary_timeout,
        )
    except SmokeError as exc:
        print(f"실패: {exc}", file=sys.stderr)
        return 1

    print("LLM dev smoke 3/3 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
