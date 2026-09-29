from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .models import Evidence, ToolResult


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_evidence(raw: Any, tool_name: str, source: str, correlation: dict[str, str] | None = None) -> list[dict[str, Any]]:
    correlation = correlation or {}
    out: list[dict[str, Any]] = []
    for item in raw or []:
        out.append({
            "evidence_id": item.get("evidence_id", str(uuid.uuid4())),
            "source_tool": tool_name,
            "source_type": item.get("source_type", "LIVE_OBSERVATION"),
            "layer": item.get("layer", "unknown"),
            "reliability_tier": item.get("reliability_tier", "LIVE_TELEMETRY"),
            "observed_at": item.get("observed_at", item.get("timestamp", now())),
            "retrieved_at": item.get("retrieved_at", now()),
            "claim": item.get("claim", ""),
            "fact_codes": list(item.get("fact_codes", [])),
            "tags": list(item.get("tags", [])),
            "correlation": dict(item.get("correlation", correlation)),
            "supports": list(item.get("supports", [])),
            "contradicts": list(item.get("contradicts", [])),
            "reliability": float(item.get("reliability", 1.0)),
            "context": item.get("context"),
            "status": item.get("status", "SUCCESS"),
        })
    return out


class ToolRuntime:
    """Capability gateway. In production, handlers call MCP/read-only APIs.
    In tests, a scenario backend may be injected. The LLM never sees the
    handler map and cannot bypass the policy registry."""

    def __init__(self, handlers: dict[str, Callable[..., Any]] | None = None):
        self.handlers = handlers or {}

    def call(self, tool_name: str, kwargs: dict[str, Any], correlation: dict[str, str] | None = None) -> ToolResult:
        started = time.monotonic()
        observed = now()
        handler = self.handlers.get(tool_name)
        if handler is None:
            return ToolResult(
                tool_name=tool_name,
                status="ERROR",
                observed_at=observed,
                retrieved_at=now(),
                source="gateway",
                correlation=correlation or {},
                error=f"Tool '{tool_name}' is not registered in the capability gateway.",
                latency_ms=(time.monotonic() - started) * 1000,
            )
        try:
            raw = handler(**kwargs)
            if isinstance(raw, ToolResult):
                return raw
            legacy_status = getattr(raw, "status", None)
            legacy_error = getattr(raw, "error", None)
            if legacy_status in {"ERROR", "TIMEOUT"}:
                return ToolResult(
                    tool_name=tool_name,
                    status=legacy_status,
                    observed_at=observed,
                    retrieved_at=now(),
                    source=tool_name,
                    correlation=correlation or {},
                    error=legacy_error or f"{tool_name} returned {legacy_status}",
                    latency_ms=(time.monotonic() - started) * 1000,
                )
            evidence = normalize_evidence(raw, tool_name, tool_name, correlation)
            status = legacy_status if legacy_status in {"SUCCESS", "NO_DATA"} else ("SUCCESS" if evidence else "NO_DATA")
            return ToolResult(
                tool_name=tool_name,
                status=status,
                observed_at=observed,
                retrieved_at=now(),
                source=tool_name,
                correlation=correlation or {},
                evidence=evidence,
                latency_ms=(time.monotonic() - started) * 1000,
            )
        except TimeoutError as exc:
            return ToolResult(
                tool_name=tool_name,
                status="TIMEOUT",
                observed_at=observed,
                retrieved_at=now(),
                source=tool_name,
                correlation=correlation or {},
                error=str(exc),
                latency_ms=(time.monotonic() - started) * 1000,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_name=tool_name,
                status="ERROR",
                observed_at=observed,
                retrieved_at=now(),
                source=tool_name,
                correlation=correlation or {},
                error=str(exc),
                latency_ms=(time.monotonic() - started) * 1000,
            )
