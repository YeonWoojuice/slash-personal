import json

import httpx
import pytest

from scripts import smoke_dev


def success_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok", "model": smoke_dev.DEFAULT_MODEL})
    if request.url.path == "/ready":
        return httpx.Response(200, json={"status": "ready", "model": smoke_dev.DEFAULT_MODEL})
    payload = json.loads(request.content)
    assert request.url.path == "/internal/v1/llm/summary"
    assert len("".join(payload["text"].split())) >= 150
    assert payload["requestId"] == smoke_dev.REQUEST_ID
    assert payload["taskId"] == smoke_dev.TASK_ID
    return httpx.Response(
        200,
        json={
            "summary": "검증용 요약 결과",
            "model": smoke_dev.DEFAULT_MODEL,
            "requestId": smoke_dev.REQUEST_ID,
            "taskId": smoke_dev.TASK_ID,
        },
    )


def test_run_smoke_verifies_health_readiness_and_summary(capsys, monkeypatch) -> None:
    clock = iter([10.0, 12.345])
    monkeypatch.setattr(smoke_dev.time, "monotonic", lambda: next(clock))

    smoke_dev.run_smoke(
        "http://llm.test",
        transport=httpx.MockTransport(success_handler),
    )

    output = capsys.readouterr().out
    assert "✓ /health" in output
    assert "✓ /ready (gemma3:4b)" in output
    assert "✓ /summary (model 및 추적 ID 확인, 2.35s)" in output
    assert smoke_dev.SMOKE_TEXT not in output
    assert "검증용 요약 결과" not in output


@pytest.mark.parametrize(
    ("status_code", "payload", "expected"),
    [
        (
            503,
            {
                "status": "not_ready",
                "model": "gemma3:4b",
                "reason": "MODEL_NOT_FOUND",
            },
            "MODEL_NOT_FOUND",
        ),
        (503, {"error": {"code": "MODEL_UNAVAILABLE"}}, "MODEL_UNAVAILABLE"),
    ],
)
def test_run_smoke_reports_stable_failure_code(status_code, payload, expected) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "model": smoke_dev.DEFAULT_MODEL})
        return httpx.Response(status_code, json=payload)

    with pytest.raises(smoke_dev.SmokeError, match=expected):
        smoke_dev.run_smoke(
            "http://llm.test",
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.parametrize(
    ("path", "payload", "expected"),
    [
        ("/health", {"status": "down", "model": "gemma3:4b"}, "/health 상태"),
        ("/health", {"status": "ok", "model": "other"}, "/health 모델"),
        ("/ready", {"status": "not_ready", "model": "gemma3:4b"}, "/ready 상태"),
        ("/ready", {"status": "ready", "model": "other"}, "/ready 모델"),
    ],
)
def test_run_smoke_distinguishes_status_and_model_mismatches(
    path, payload, expected
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == path:
            return httpx.Response(200, json=payload)
        return success_handler(request)

    with pytest.raises(smoke_dev.SmokeError, match=expected):
        smoke_dev.run_smoke(
            "http://llm.test",
            transport=httpx.MockTransport(handler),
        )


def test_run_smoke_rejects_tracking_id_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "model": smoke_dev.DEFAULT_MODEL})
        if request.url.path == "/ready":
            return httpx.Response(200, json={"status": "ready", "model": smoke_dev.DEFAULT_MODEL})
        return httpx.Response(
            200,
            json={
                "summary": "검증용 요약 결과",
                "model": smoke_dev.DEFAULT_MODEL,
                "requestId": "wrong-request",
                "taskId": smoke_dev.TASK_ID,
            },
        )

    with pytest.raises(smoke_dev.SmokeError, match="추적 ID"):
        smoke_dev.run_smoke(
            "http://llm.test",
            transport=httpx.MockTransport(handler),
        )


def test_run_smoke_normalizes_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private address must not leak", request=request)

    with pytest.raises(smoke_dev.SmokeError, match="ConnectError") as captured:
        smoke_dev.run_smoke(
            "http://llm.test",
            transport=httpx.MockTransport(handler),
        )

    assert "private address must not leak" not in str(captured.value)


def test_run_smoke_uses_separate_probe_and_summary_timeouts() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured[request.url.path] = request.extensions["timeout"]["read"]
        return success_handler(request)

    smoke_dev.run_smoke(
        "http://llm.test",
        probe_timeout=3,
        summary_timeout=150,
        transport=httpx.MockTransport(handler),
    )

    assert captured["/health"] == 3
    assert captured["/ready"] == 3
    assert captured["/internal/v1/llm/summary"] == 150


@pytest.mark.parametrize("base_url", ["slash-llm", "ftp://slash-llm"])
def test_run_smoke_requires_http_url(base_url: str) -> None:
    with pytest.raises(smoke_dev.SmokeError, match="http 또는 https"):
        smoke_dev.run_smoke(base_url, transport=httpx.MockTransport(success_handler))


def test_main_requires_deployed_base_url(monkeypatch, capsys) -> None:
    monkeypatch.delenv("LLM_SMOKE_BASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["smoke_dev.py"])

    assert smoke_dev.main() == 2
    assert "LLM_SMOKE_BASE_URL" in capsys.readouterr().err


@pytest.mark.parametrize(
    "variable",
    ["LLM_SMOKE_PROBE_TIMEOUT", "LLM_SMOKE_SUMMARY_TIMEOUT"],
)
@pytest.mark.parametrize("value", ["invalid", "nan", "inf", "-inf", "0", "-1"])
def test_main_rejects_invalid_timeout_environment(
    variable, value, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("LLM_SMOKE_BASE_URL", "http://llm.test")
    monkeypatch.setenv(variable, value)
    monkeypatch.setattr("sys.argv", ["smoke_dev.py"])

    with pytest.raises(SystemExit) as captured:
        smoke_dev.main()

    assert captured.value.code == 2
    assert "0보다 큰 숫자" in capsys.readouterr().err
