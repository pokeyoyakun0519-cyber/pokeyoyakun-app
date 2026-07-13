import time
from dataclasses import dataclass
from typing import Callable, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    initial_delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 8.0

    def run(
        self,
        operation: Callable[[], T],
        *,
        should_retry: Callable[[Exception], bool] | None = None,
    ) -> T:
        attempts = max(1, int(self.attempts))
        delay = max(0.0, float(self.initial_delay_seconds))
        last_error: Exception | None = None

        for index in range(attempts):
            try:
                return operation()
            except Exception as error:
                last_error = error

                if should_retry is not None and not should_retry(error):
                    raise

                if index >= attempts - 1:
                    break

                if delay > 0:
                    time.sleep(delay)

                delay = min(
                    self.max_delay_seconds,
                    max(
                        self.initial_delay_seconds,
                        delay * self.backoff_multiplier,
                    ),
                )

        assert last_error is not None
        raise last_error
