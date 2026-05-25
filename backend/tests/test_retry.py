import pytest

from app.orchestration.retry import retry_async


async def test_retry_async_retries_until_success():
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise ValueError("try again")
        return "ok"

    result = await retry_async(flaky, attempts=3, delay_seconds=0)
    assert result == "ok"
    assert attempts == 2


async def test_retry_async_raises_last_error():
    async def always_fail() -> None:
        raise RuntimeError("failed")

    with pytest.raises(RuntimeError, match="failed"):
        await retry_async(always_fail, attempts=2, delay_seconds=0)
