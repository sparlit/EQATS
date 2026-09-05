import structlog
import logging
import sys
from collections import deque

log_buffer: deque = deque(maxlen=500)


class _BufferProcessor:
    """structlog processor that keeps recent log lines in memory.

    Feeds the dashboard's live log stream without needing a log file.
    """
    def __call__(self, logger, method, event_dict):
        log_buffer.append(dict(event_dict))
        return event_dict


def setup_logging(level: str = "INFO"):
    """Configure structlog for console output plus the in-memory buffer."""
    logging.basicConfig(
        format="%(message)s", stream=sys.stdout, level=getattr(logging, level)
    )

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            _BufferProcessor(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
