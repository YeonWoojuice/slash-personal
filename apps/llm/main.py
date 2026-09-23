"""slash-llm — HTTP 기반 Gemma 요약 서비스."""

import asyncio
import os
from typing import Any, Dict, Literal, Optional

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from summary_core import SummaryInputTooShort, build_summary_prompt, prepare_summary_text

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("LLM_MODEL", "gemma3:4b")
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))
READY_TIMEOUT = float(os.getenv("LLM_READY_TIMEOUT", "2"))

# 입력 제한
# 짧은 글을 요약시키면 모델이 3줄을 채우려고 원문보다 길게 늘여 쓴다.
# 그런 입력은 애초에 요약 대상이 아니므로 여기서 막는다.
MIN_CHARS = int(os.getenv("SUMMARY_MIN_CHARS", "150"))
MAX_CHARS = int(os.getenv("SUMMARY_MAX_CHARS", "8000"))
MAX_CONCURRENT_REQUESTS = max(
    1,
    int(os.getenv("LLM_MAX_CONCURRENT_REQUESTS", "1")),
)
RETRY_AFTER_SECONDS = max(1, int(os.getenv("LLM_BUSY_RETRY_AFTER", "1")))

app = FastAPI(title="slash-llm")
inference_slots = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)


class SummaryRequest(BaseModel):
    text: str
    requestId: Optional[str] = None
    taskId: Optional[str] = None


class SummaryResponse(BaseModel):
    summary: str
    model: str
    requestId: Optional[str] = None
    taskId: Optional[str] = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool


class ErrorResponse(BaseModel):
    error: ErrorDetail
    requestId: Optional[str] = None
    taskId: Optional[str] = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    model: str
    reason: Optional[Literal["OLLAMA_UNAVAILABLE", "MODEL_NOT_FOUND"]] = None


class ModelServiceError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = ErrorDetail(
            code=code,
            message=message,
            retryable=retryable,
        )


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL}


def create_ollama_readiness_client() -> httpx.AsyncClient:
    """Readiness probe가 추론 timeout만큼 대기하지 않도록 짧게 제한한다."""
    return httpx.AsyncClient(timeout=READY_TIMEOUT)


@app.get(
    "/ready",
    response_model=ReadinessResponse,
    response_model_exclude_none=True,
    responses={503: {"model": ReadinessResponse, "description": "Ollama 준비 안 됨"}},
)
async def ready():
    try:
        async with create_ollama_readiness_client() as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            response.raise_for_status()
            payload: Any = response.json()
    except (httpx.HTTPError, ValueError):
        return JSONResponse(
            status_code=503,
            content=ReadinessResponse(
                status="not_ready",
                model=MODEL,
                reason="OLLAMA_UNAVAILABLE",
            ).model_dump(exclude_none=True),
        )

    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return JSONResponse(
            status_code=503,
            content=ReadinessResponse(
                status="not_ready",
                model=MODEL,
                reason="OLLAMA_UNAVAILABLE",
            ).model_dump(exclude_none=True),
        )

    available_models = {
        model_name
        for item in models
        if isinstance(item, dict)
        for model_name in (item.get("name"), item.get("model"))
        if isinstance(model_name, str)
    }
    if MODEL not in available_models:
        return JSONResponse(
            status_code=503,
            content=ReadinessResponse(
                status="not_ready",
                model=MODEL,
                reason="MODEL_NOT_FOUND",
            ).model_dump(exclude_none=True),
        )

    return ReadinessResponse(status="ready", model=MODEL)


def create_ollama_client() -> httpx.AsyncClient:
    """테스트에서 실제 Ollama 없이 교체할 수 있는 client 생성 경계."""
    return httpx.AsyncClient(timeout=TIMEOUT)


async def ask_gemma(prompt: str) -> str:
    """Ollama 응답을 검증하고 예측 가능한 내부 오류로 정규화한다."""
    try:
        async with create_ollama_client() as client:
            res = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": MODEL, "prompt": prompt, "stream": False},
            )
            res.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ModelServiceError(
            status_code=504,
            code="MODEL_TIMEOUT",
            message="모델 응답 시간이 초과되었다.",
            retryable=True,
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ModelServiceError(
            status_code=502,
            code="UPSTREAM_ERROR",
            message="모델 서버가 오류 응답을 반환했다.",
            retryable=True,
        ) from exc
    except httpx.RequestError as exc:
        raise ModelServiceError(
            status_code=503,
            code="MODEL_UNAVAILABLE",
            message="모델 서버에 연결할 수 없다.",
            retryable=True,
        ) from exc

    try:
        payload: Any = res.json()
    except ValueError as exc:
        raise ModelServiceError(
            status_code=502,
            code="INVALID_MODEL_RESPONSE",
            message="모델 서버 응답을 해석할 수 없다.",
            retryable=True,
        ) from exc

    response = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(response, str) or not response.strip():
        raise ModelServiceError(
            status_code=502,
            code="INVALID_MODEL_RESPONSE",
            message="모델 서버 응답에 유효한 결과가 없다.",
            retryable=True,
        )
    return response.strip()


def build_error_response(
    *,
    status_code: int,
    detail: ErrorDetail,
    request_id: Optional[str],
    task_id: Optional[str],
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=detail,
        requestId=request_id,
        taskId=task_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        headers=headers,
    )


@app.post(
    "/internal/v1/llm/summary",
    response_model=SummaryResponse,
    response_model_exclude_none=True,
    responses={
        400: {"model": ErrorResponse, "description": "요약 입력 길이 오류"},
        502: {"model": ErrorResponse, "description": "잘못된 Ollama 응답"},
        503: {"model": ErrorResponse, "description": "모델 연결 실패 또는 서비스 과부하"},
        504: {"model": ErrorResponse, "description": "Ollama 응답 시간 초과"},
    },
)
async def summary(req: SummaryRequest):
    try:
        text = prepare_summary_text(req.text, minimum=MIN_CHARS, maximum=MAX_CHARS)
    except SummaryInputTooShort as exc:
        return build_error_response(
            status_code=400,
            detail=ErrorDetail(
                code="INPUT_TOO_SHORT",
                message=str(exc),
                retryable=False,
            ),
            request_id=req.requestId,
            task_id=req.taskId,
        )
    prompt = build_summary_prompt(text)

    # 사용자/IP 단위 rate limit은 slash-api가 담당한다. 여기서는 비싼 모델
    # 호출이 프로세스 처리 용량을 넘지 않도록 대기열 없이 즉시 거절한다.
    if inference_slots.locked():
        return build_error_response(
            status_code=503,
            detail=ErrorDetail(
                code="MODEL_BUSY",
                message="모델 서비스가 처리 가능한 동시 요청 수를 초과했다.",
                retryable=True,
            ),
            request_id=req.requestId,
            task_id=req.taskId,
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        )

    await inference_slots.acquire()
    try:
        try:
            result = await ask_gemma(prompt)
        except ModelServiceError as exc:
            return build_error_response(
                status_code=exc.status_code,
                detail=exc.detail,
                request_id=req.requestId,
                task_id=req.taskId,
            )
    finally:
        inference_slots.release()

    return SummaryResponse(
        summary=result,
        model=MODEL,
        requestId=req.requestId,
        taskId=req.taskId,
    )
