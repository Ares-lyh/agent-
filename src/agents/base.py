"""Base Agent class and common resilience utilities."""
import time
import random
from typing import Callable, Any
from src.core.exceptions import RateLimitExceededError, ModelTimeoutError


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 0.2,
    backoff_factor: float = 2.0,
    jitter: bool = True,
):
    """Decorator to retry flaky network calls with exponential backoff and jitter."""
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (RateLimitExceededError, ModelTimeoutError) as e:
                    last_exception = e
                    if attempt == max_retries:
                        raise
                    sleep_time = delay + (random.uniform(0.01, 0.1) if jitter else 0.0)
                    time.sleep(sleep_time)
                    delay *= backoff_factor
            raise last_exception or RuntimeError("重试次数耗尽")
        return wrapper
    return decorator


class BaseAgent:
    """Base class for all system agents."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
