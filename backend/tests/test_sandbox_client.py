import pytest

from models.sandbox import SandboxExecutionRequest
from services.sandbox.client import SandboxClient, SandboxClientError


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        return self.payload


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, json):
        self.posts.append((url, json))
        return self.response


@pytest.mark.asyncio
async def test_sandbox_client_executes_request(monkeypatch):
    fake_client = FakeAsyncClient(
        FakeResponse(
            {
                "ok": True,
                "summary": "completed",
                "stdout": "hello",
                "stderr": "",
                "result": {"count": 1},
                "artifacts": [],
                "geojson_outputs": [],
            }
        )
    )

    monkeypatch.setattr(
        "services.sandbox.client.httpx.AsyncClient",
        lambda timeout: fake_client,
    )

    client = SandboxClient(base_url="http://sandbox:8080", timeout=3)
    response = await client.execute(SandboxExecutionRequest(analysis_goal="test"))

    assert response.ok is True
    assert response.result == {"count": 1}
    assert fake_client.posts[0][0] == "http://sandbox:8080/execute"
    assert fake_client.posts[0][1]["analysis_goal"] == "test"


@pytest.mark.asyncio
async def test_sandbox_client_requires_base_url():
    client = SandboxClient(base_url="")

    with pytest.raises(SandboxClientError):
        await client.execute(SandboxExecutionRequest(analysis_goal="test"))
