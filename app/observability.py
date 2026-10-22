import json
import logging
from contextvars import ContextVar
from decimal import Decimal

from app.models import Event, now

logger = logging.getLogger("impact.events")
current_request: ContextVar[str | None] = ContextVar("current_request", default=None)
current_run: ContextVar[str | None] = ContextVar("current_run", default=None)


def emit(
    session,
    stage,
    operation,
    status,
    *,
    run_id=None,
    request_id=None,
    resource_id=None,
    duration_ms=None,
    error_code=None,
    **safe,
):
    """Only call-site supplied counters, codes and IDs belong here, never source text."""
    request_id = request_id or current_request.get()
    run_id = run_id or current_run.get()
    entry = Event(
        stage=stage,
        operation=operation,
        status=status,
        run_id=run_id,
        request_id=request_id,
        resource_id=resource_id,
        duration_ms=duration_ms,
        error_code=error_code,
        safe_metadata=safe,
    )
    session.add(entry)
    logger.info(
        json.dumps(
            {
                "timestamp": now().isoformat(),
                "stage": stage,
                "operation": operation,
                "status": status,
                "run_id": run_id,
                "request_id": request_id,
                "resource_id": resource_id,
                "error_code": error_code,
                "duration_ms": duration_ms,
                "safe_metadata": safe,
            }
        )
    )
    return entry


def cost_summary(usage):
    """A partial estimate never silently turns unknown entries into free calls."""
    groups = {}
    for entry in usage:
        for dimension, key in (
            ("provider", entry.provider),
            ("operation", entry.operation),
            ("run", entry.run_id),
            ("overall", "all"),
        ):
            group = groups.setdefault(
                (dimension, key),
                {
                    "dimension": dimension,
                    "key": key,
                    "known_estimate_usd": Decimal("0"),
                    "unknown_calls": 0,
                    "calls": 0,
                },
            )
            group["calls"] += 1
            if entry.estimated_usd is None:
                group["unknown_calls"] += 1
            else:
                group["known_estimate_usd"] += entry.estimated_usd
    return [
        {**group, "known_estimate_usd": str(group["known_estimate_usd"])}
        for group in groups.values()
    ]
