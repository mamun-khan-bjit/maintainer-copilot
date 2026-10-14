import logging
import uuid

import structlog


def configure_logging(level: int = logging.INFO) -> None:
    """One JSON object per log line, with any bound context (like request_id) merged in."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # adds request_id etc. bound for this request
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )


def new_request_id() -> str:
    return uuid.uuid4().hex
