import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def install_ollama_transport(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    def client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, timeout=main.TIMEOUT)

    monkeypatch.setattr(main, "create_ollama_client", client_factory)


def install_readiness_transport(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    def client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, timeout=main.READY_TIMEOUT)

    monkeypatch.setattr(main, "create_ollama_readiness_client", client_factory)


def test_health_keeps_static_status_and_model(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": main.MODEL}


@pytest.mark.parametrize("model_field", ["name", "model"])
def test_ready_when_ollama_has_configured_model(
    client: TestClient,
    monkeypatch,
    model_field: str,
) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"models": [{model_field: main.MODEL}]})

    install_readiness_transport(monkeypatch, handler)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "model": main.MODEL}
    assert captured["url"] == f"{main.OLLAMA_URL}/api/tags"


def test_ready_returns_503_when_model_is_missing(
    client: TestClient,
    monkeypatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "another-model"}]})

    install_readiness_transport(monkeypatch, handler)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "model": main.MODEL,
        "reason": "MODEL_NOT_FOUND",
    }


@pytest.mark.parametrize(
    "failure",
    ["connection", "timeout", "http_error", "invalid_json", "invalid_models"],
)
def test_ready_returns_503_when_ollama_is_unavailable(
    client: TestClient,
    monkeypatch,
    failure: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "connection":
            raise httpx.ConnectError("connection failed", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if failure == "http_error":
            return httpx.Response(500, json={"error": "server error"})
        if failure == "invalid_json":
            return httpx.Response(200, content=b"not-json")
        return httpx.Response(200, json={"models": "invalid"})

    install_readiness_transport(monkeypatch, handler)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "model": main.MODEL,
        "reason": "OLLAMA_UNAVAILABLE",
    }


def test_149_characters_returns_stable_error(client: TestClient) -> None:
    response = client.post(
        "/internal/v1/llm/summary",
        json={"text": "가" * 149},
    )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "INPUT_TOO_SHORT",
        "message": "요약할 만큼 긴 글이 아니다 (149자, 최소 150자).",
        "retryable": False,
    }
    assert "requestId" not in response.json()
    assert "taskId" not in response.json()


def test_input_error_returns_tracking_ids(client: TestClient) -> None:
    response = client.post(
        "/internal/v1/llm/summary",
        json={
            "text": "짧다",
            "requestId": "request-1",
            "taskId": "task-1",
        },
    )

    assert response.status_code == 400
    assert response.json()["requestId"] == "request-1"
    assert response.json()["taskId"] == "task-1"


@pytest.mark.parametrize("length", [150, 8000])
def test_minimum_and_maximum_boundaries_are_accepted(
    client: TestClient,
    monkeypatch,
    length: int,
) -> None:
    captured = {}

    async def fake_ask(prompt: str) -> str:
        captured["prompt"] = prompt
        return "요약 결과"

    monkeypatch.setattr(main, "ask_gemma", fake_ask)
    text = "가" * length

    response = client.post(
        "/internal/v1/llm/summary",
        json={"text": text},
    )

    assert response.status_code == 200
    assert response.json() == {"summary": "요약 결과", "model": main.MODEL}
    assert captured["prompt"].endswith(text)


def test_8001_characters_are_truncated_to_8000(
    client: TestClient,
    monkeypatch,
) -> None:
    captured = {}

    async def fake_ask(prompt: str) -> str:
        captured["prompt"] = prompt
        return "요약 결과"

    monkeypatch.setattr(main, "ask_gemma", fake_ask)

    response = client.post(
        "/internal/v1/llm/summary",
        json={"text": ("가" * 8000) + "나"},
    )

    assert response.status_code == 200
    assert captured["prompt"].endswith("가" * 8000)
    assert not captured["prompt"].endswith("나")


def test_length_boundary_is_calculated_after_strip(
    client: TestClient,
    monkeypatch,
) -> None:
    captured = {}

    async def fake_ask(prompt: str) -> str:
        captured["prompt"] = prompt
        return "요약 결과"

    monkeypatch.setattr(main, "ask_gemma", fake_ask)
    accepted = client.post(
        "/internal/v1/llm/summary",
        json={"text": f"  {'가' * 150}\n"},
    )
    rejected = client.post(
        "/internal/v1/llm/summary",
        json={"text": f"  {'가' * 149}\n"},
    )

    assert accepted.status_code == 200
    assert captured["prompt"].endswith("가" * 150)
    assert rejected.status_code == 400


def test_success_returns_tracking_ids(client: TestClient, monkeypatch) -> None:
    async def fake_ask(prompt: str) -> str:
        return "요약 결과"

    monkeypatch.setattr(main, "ask_gemma", fake_ask)

    response = client.post(
        "/internal/v1/llm/summary",
        json={
            "text": "가" * 150,
            "requestId": "request-1",
            "taskId": "task-1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "summary": "요약 결과",
        "model": main.MODEL,
        "requestId": "request-1",
        "taskId": "task-1",
    }


def test_ollama_payload_and_response_are_preserved(
    client: TestClient,
    monkeypatch,
) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "  요약 결과  "})

    install_ollama_transport(monkeypatch, handler)
    text = "가" * 150

    response = client.post(
        "/internal/v1/llm/summary",
        json={"text": text},
    )

    assert response.status_code == 200
    assert response.json()["summary"] == "요약 결과"
    assert captured["url"] == f"{main.OLLAMA_URL}/api/generate"
    assert captured["json"]["model"] == main.MODEL
    assert captured["json"]["stream"] is False
    assert captured["json"]["prompt"].endswith(text)


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    [
        ("connection", 503, "MODEL_UNAVAILABLE"),
        ("timeout", 504, "MODEL_TIMEOUT"),
        ("http_400", 502, "UPSTREAM_ERROR"),
        ("http_500", 502, "UPSTREAM_ERROR"),
        ("invalid_json", 502, "INVALID_MODEL_RESPONSE"),
        ("missing_response", 502, "INVALID_MODEL_RESPONSE"),
        ("empty_response", 502, "INVALID_MODEL_RESPONSE"),
    ],
)
def test_ollama_failures_return_stable_errors_and_tracking_ids(
    client: TestClient,
    monkeypatch,
    failure: str,
    expected_status: int,
    expected_code: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "connection":
            raise httpx.ConnectError("connection failed", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if failure == "http_400":
            return httpx.Response(400, json={"error": "bad request"})
        if failure == "http_500":
            return httpx.Response(500, json={"error": "server error"})
        if failure == "invalid_json":
            return httpx.Response(200, content=b"not-json")
        if failure == "missing_response":
            return httpx.Response(200, json={"done": True})
        return httpx.Response(200, json={"response": "   "})

    install_ollama_transport(monkeypatch, handler)

    response = client.post(
        "/internal/v1/llm/summary",
        json={
            "text": "가" * 150,
            "requestId": "request-1",
            "taskId": "task-1",
        },
    )

    assert response.status_code == expected_status
    body = response.json()
    assert body["error"]["code"] == expected_code
    assert body["error"]["retryable"] is True
    assert body["requestId"] == "request-1"
    assert body["taskId"] == "task-1"


def test_pydantic_validation_keeps_default_422(client: TestClient) -> None:
    response = client.post(
        "/internal/v1/llm/summary",
        json={},
    )

    assert response.status_code == 422
    assert "detail" in response.json()


def test_concurrency_limit_returns_model_busy_with_retry_after(monkeypatch) -> None:
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_ask(prompt: str) -> str:
            started.set()
            await release.wait()
            return "요약 결과"

        monkeypatch.setattr(main, "ask_gemma", slow_ask)
        monkeypatch.setattr(main, "inference_slots", asyncio.Semaphore(1))
        monkeypatch.setattr(main, "RETRY_AFTER_SECONDS", 2)

        first = asyncio.create_task(
            main.summary(main.SummaryRequest(text="가" * 150, requestId="request-1"))
        )
        await started.wait()
        busy = await main.summary(
            main.SummaryRequest(text="나" * 150, requestId="request-2")
        )

        assert busy.status_code == 503
        assert busy.headers["retry-after"] == "2"
        body = json.loads(busy.body)
        assert body["error"] == {
            "code": "MODEL_BUSY",
            "message": "모델 서비스가 처리 가능한 동시 요청 수를 초과했다.",
            "retryable": True,
        }
        assert body["requestId"] == "request-2"

        release.set()
        completed = await first
        assert completed.summary == "요약 결과"

    asyncio.run(scenario())


def test_openapi_exposes_success_and_stable_error_contracts() -> None:
    operation = main.app.openapi()["paths"]["/internal/v1/llm/summary"]["post"]
    assert {"200", "400", "422", "502", "503", "504"} <= set(operation["responses"])
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]
    for status_code in ("400", "502", "503", "504"):
        schema = operation["responses"][status_code]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse")


def test_openapi_exposes_readiness_contract() -> None:
    operation = main.app.openapi()["paths"]["/ready"]["get"]

    assert {"200", "503"} <= set(operation["responses"])
    for status_code in ("200", "503"):
        schema = operation["responses"][status_code]["content"]["application/json"][
            "schema"
        ]
        assert schema["$ref"].endswith("/ReadinessResponse")


def test_internal_contract_does_not_copy_public_backend_envelope(
    client: TestClient,
    monkeypatch,
) -> None:
    async def fake_ask(prompt: str) -> str:
        return "요약 결과"

    monkeypatch.setattr(main, "ask_gemma", fake_ask)
    success = client.post(
        "/internal/v1/llm/summary",
        json={"text": "가" * 150, "requestId": "correlation-1", "taskId": "task-1"},
    ).json()
    error = client.post(
        "/internal/v1/llm/summary",
        json={"text": "짧다", "requestId": "correlation-2", "taskId": "task-2"},
    ).json()

    assert "data" not in success and "meta" not in success
    assert "meta" not in error
    assert success["requestId"] == "correlation-1"
    assert error["requestId"] == "correlation-2"
