"""Worker entrypoint: `openquyhoach-worker [--once]`.

All registrations must be imported before the loop starts; handler
registry is process-local.
"""

from __future__ import annotations

import sys

from openquyhoach_core.logging import configure_logging, get_logger
from openquyhoach_core.settings import get_settings


def main() -> None:
    configure_logging(get_settings().log_level, get_settings().log_format)
    log = get_logger(__name__)

    import openquyhoach_ingest.jobs  # noqa: F401

    import openquyhoach_worker.jobs  # noqa: F401

    once = "--once" in sys.argv
    backend = get_settings().queue_backend
    if backend == "redis":
        from openquyhoach_core.queue import RedisQueue

        RedisQueue().worker_loop(once=once)
    else:
        # Inline mode: nothing to poll — jobs run inside the caller's process.
        log.info("worker.inline_mode", note="queue_backend=inline; exiting")
    sys.exit(0)


if __name__ == "__main__":
    main()
