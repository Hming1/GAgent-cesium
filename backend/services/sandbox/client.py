import logging
from typing import Optional

import httpx

from core.config import PYTHON_ANALYSIS_SANDBOX_TIMEOUT, PYTHON_ANALYSIS_SANDBOX_URL
from models.sandbox import SandboxExecutionRequest, SandboxExecutionResponse

logger = logging.getLogger(__name__)


class SandboxClientError(RuntimeError):
    """Raised when the Python analysis sandbox cannot complete a request."""


class SandboxClient:
    """HTTP client for the isolated Python analysis sandbox service."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.base_url = (base_url if base_url is not None else PYTHON_ANALYSIS_SANDBOX_URL).rstrip(
            "/"
        )
        self.timeout = timeout if timeout is not None else PYTHON_ANALYSIS_SANDBOX_TIMEOUT

    async def execute(self, request: SandboxExecutionRequest) -> SandboxExecutionResponse:
        """Execute an analysis request in the sandbox."""

        if not self.base_url:
            raise SandboxClientError(
                "Python analysis sandbox is not configured. "
                "Set PYTHON_ANALYSIS_SANDBOX_URL to enable run_python_analysis."
            )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/execute",
                    json=request.model_dump(mode="json"),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Python analysis sandbox request failed: %s", exc)
            raise SandboxClientError(f"Python analysis sandbox request failed: {exc}") from exc

        try:
            return SandboxExecutionResponse.model_validate(response.json())
        except Exception as exc:
            logger.warning("Invalid Python analysis sandbox response: %s", exc)
            raise SandboxClientError(
                "Python analysis sandbox returned an invalid response"
            ) from exc


async def execute_python_analysis(
    request: SandboxExecutionRequest,
    client: Optional[SandboxClient] = None,
) -> SandboxExecutionResponse:
    """Execute Python analysis through the configured sandbox client."""

    sandbox_client = client or SandboxClient()
    return await sandbox_client.execute(request)
