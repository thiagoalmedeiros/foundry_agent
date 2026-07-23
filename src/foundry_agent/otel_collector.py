"""A minimal OTLP/HTTP collector that persists to the AI Toolkit trace store.

The Foundry hosting SDK's OTel distro exports over OTLP/HTTP to
``OTEL_EXPORTER_OTLP_ENDPOINT`` (``http://localhost:4318`` locally). Normally
the receiving end is the VS Code AI Toolkit extension's own collector, which
writes ``~/.aitk/tracing/traces.db`` for its trace viewer. That collector is an
extension process a shell task cannot start, so ``task hosted:run`` can never
*guarantee* it is up.

This module is a self-contained stand-in: a stdlib HTTP server that accepts the
same OTLP/HTTP protobuf the distro sends, decodes it with ``opentelemetry-proto``,
and writes the **same** ``traces.db`` schema the AI Toolkit viewer reads — so
traces show up in exactly the same place, whether the extension is running or
not. It is started by ``task otel:up`` only when nothing already holds ``:4318``
(see the Taskfile), so it never fights the real AI Toolkit collector for the
port.

Scope: local developer observability only. It is deliberately not a
general-purpose collector — no sampling, batching, or retention — and is never
part of a deployed Foundry environment, where the platform's own Azure Monitor
wiring receives traces instead.
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import os
import sqlite3
import threading
from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
    ExportMetricsServiceResponse,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue

logger = logging.getLogger(__name__)

DEFAULT_PORT = 4318
#: Where the AI Toolkit trace viewer reads from; override with ``AITK_TRACES_DB``.
DEFAULT_DB_PATH = Path.home() / ".aitk" / "tracing" / "traces.db"
_UNSET_SERVICE_NAME = "unknown_service"

# The exact schema the AI Toolkit viewer expects. Created only when absent, so a
# store the extension already populated is reused untouched.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL, span_id TEXT NOT NULL, name TEXT NOT NULL,
    parent_span_id TEXT, service_name TEXT NOT NULL, kind INTEGER DEFAULT 0,
    start_time INTEGER NOT NULL, end_time INTEGER, duration INTEGER,
    attributes TEXT, events TEXT, resource_attributes TEXT, resource_schema_url TEXT,
    span_links TEXT, status_code INTEGER, status_message TEXT,
    created_at INTEGER DEFAULT (strftime('%s', 'now'))
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER, observed_timestamp INTEGER, trace_id TEXT, span_id TEXT,
    trace_flags INTEGER, body TEXT, attributes TEXT,
    dropped_attributes_count INTEGER DEFAULT 0, severity_number INTEGER,
    severity_text TEXT, resource_attributes TEXT, resource_schema_url TEXT,
    scope_name TEXT, scope_version TEXT, scope_attributes TEXT, scope_schema_url TEXT,
    service_name TEXT NOT NULL, created_at INTEGER DEFAULT (strftime('%s', 'now'))
);
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, description TEXT, unit TEXT, type TEXT NOT NULL,
    timestamp INTEGER, value REAL, attributes TEXT, resource_attributes TEXT,
    resource_schema_url TEXT, scope_name TEXT, scope_version TEXT,
    scope_attributes TEXT, scope_schema_url TEXT, service_name TEXT NOT NULL,
    data TEXT, created_at INTEGER DEFAULT (strftime('%s', 'now'))
);
"""


def _b64(raw: bytes) -> str | None:
    """Encode raw trace/span-id bytes the way the AI Toolkit store does.

    The store keeps ids as base64 of the raw bytes (not hex); an empty id — a
    span with no parent, say — is stored as ``NULL`` rather than ``""``.
    """
    return base64.b64encode(raw).decode("ascii") if raw else None


def _ns_to_ms(unix_nano: int) -> int:
    """Convert an OTLP unix-nanosecond timestamp to the store's millisecond unit."""
    return unix_nano // 1_000_000


def _anyvalue_to_native(value: AnyValue) -> Any:
    """Unwrap an OTLP ``AnyValue`` into a JSON-native Python value.

    The store flattens attributes to ``{key: nativeValue}`` rather than keeping
    the protobuf ``AnyValue`` envelope, so each variant maps to its plain type;
    bytes (which JSON cannot hold) are base64-encoded.
    """
    which = value.WhichOneof("value")
    if which == "string_value":
        return value.string_value
    if which == "bool_value":
        return value.bool_value
    if which == "int_value":
        return value.int_value
    if which == "double_value":
        return value.double_value
    if which == "array_value":
        return [_anyvalue_to_native(v) for v in value.array_value.values]
    if which == "kvlist_value":
        return _kv_to_dict(value.kvlist_value.values)
    if which == "bytes_value":
        return base64.b64encode(value.bytes_value).decode("ascii")
    return None


def _kv_to_dict(pairs: Iterable[KeyValue]) -> dict[str, Any]:
    """Flatten a repeated OTLP ``KeyValue`` field into a plain dict."""
    return {pair.key: _anyvalue_to_native(pair.value) for pair in pairs}


def _service_name(resource_attrs: dict[str, Any]) -> str:
    """Resolve ``service.name`` from resource attributes, matching OTLP's fallback."""
    name = resource_attrs.get("service.name")
    return name if isinstance(name, str) and name else _UNSET_SERVICE_NAME


class TraceStore:
    """Serialised writer for the AI Toolkit ``traces.db`` SQLite store.

    The server is multithreaded, so every write is guarded by a lock and uses a
    short-lived connection in WAL mode — WAL lets the AI Toolkit viewer read the
    store concurrently without blocking these writes.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def write_spans(self, request: ExportTraceServiceRequest) -> int:
        """Persist every span in an OTLP trace-export request; return the count."""
        rows: list[tuple[Any, ...]] = []
        for resource_spans in request.resource_spans:
            res_attrs = _kv_to_dict(resource_spans.resource.attributes)
            service = _service_name(res_attrs)
            res_json = json.dumps(res_attrs)
            for scope_spans in resource_spans.scope_spans:
                for span in scope_spans.spans:
                    start_ms = _ns_to_ms(span.start_time_unix_nano)
                    end_ms = _ns_to_ms(span.end_time_unix_nano) if span.end_time_unix_nano else None
                    rows.append(
                        (
                            _b64(span.trace_id),
                            _b64(span.span_id),
                            span.name,
                            _b64(span.parent_span_id),
                            service,
                            span.kind,
                            start_ms,
                            end_ms,
                            (end_ms - start_ms) if end_ms is not None else None,
                            json.dumps(_kv_to_dict(span.attributes)),
                            json.dumps(self._events(span)),
                            res_json,
                            resource_spans.schema_url or None,
                            json.dumps(self._links(span)),
                            span.status.code,
                            span.status.message or None,
                        )
                    )
        self._insert(
            "INSERT INTO spans (trace_id, span_id, name, parent_span_id, service_name, "
            "kind, start_time, end_time, duration, attributes, events, "
            "resource_attributes, resource_schema_url, span_links, status_code, "
            "status_message) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        return len(rows)

    @staticmethod
    def _events(span: Any) -> list[dict[str, Any]]:
        return [
            {
                "name": event.name,
                "timestamp": _ns_to_ms(event.time_unix_nano),
                "attributes": _kv_to_dict(event.attributes),
            }
            for event in span.events
        ]

    @staticmethod
    def _links(span: Any) -> list[dict[str, Any]]:
        return [
            {
                "trace_id": _b64(link.trace_id),
                "span_id": _b64(link.span_id),
                "attributes": _kv_to_dict(link.attributes),
            }
            for link in span.links
        ]

    def write_logs(self, request: ExportLogsServiceRequest) -> int:
        """Persist every log record in an OTLP logs-export request; return the count."""
        rows: list[tuple[Any, ...]] = []
        for resource_logs in request.resource_logs:
            res_attrs = _kv_to_dict(resource_logs.resource.attributes)
            service = _service_name(res_attrs)
            res_json = json.dumps(res_attrs)
            for scope_logs in resource_logs.scope_logs:
                scope = scope_logs.scope
                for record in scope_logs.log_records:
                    rows.append(
                        (
                            _ns_to_ms(record.time_unix_nano) if record.time_unix_nano else None,
                            _ns_to_ms(record.observed_time_unix_nano)
                            if record.observed_time_unix_nano
                            else None,
                            _b64(record.trace_id),
                            _b64(record.span_id),
                            record.flags,
                            json.dumps(_anyvalue_to_native(record.body)),
                            json.dumps(_kv_to_dict(record.attributes)),
                            record.dropped_attributes_count,
                            record.severity_number,
                            record.severity_text or None,
                            res_json,
                            resource_logs.schema_url or None,
                            scope.name or None,
                            scope.version or None,
                            json.dumps(_kv_to_dict(scope.attributes)),
                            scope_logs.schema_url or None,
                            service,
                        )
                    )
        self._insert(
            "INSERT INTO logs (timestamp, observed_timestamp, trace_id, span_id, "
            "trace_flags, body, attributes, dropped_attributes_count, severity_number, "
            "severity_text, resource_attributes, resource_schema_url, scope_name, "
            "scope_version, scope_attributes, scope_schema_url, service_name) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        return len(rows)

    def write_metrics(self, request: ExportMetricsServiceRequest) -> int:
        """Persist number data points from an OTLP metrics-export request.

        Gauges and sums map to one row per data point with a scalar ``value``;
        histograms and summaries are stored as their JSON blob in ``data`` with a
        ``NULL`` scalar, matching the store's ``value``/``data`` split.
        """
        rows: list[tuple[Any, ...]] = []
        for resource_metrics in request.resource_metrics:
            res_attrs = _kv_to_dict(resource_metrics.resource.attributes)
            service = _service_name(res_attrs)
            res_json = json.dumps(res_attrs)
            for scope_metrics in resource_metrics.scope_metrics:
                scope = scope_metrics.scope
                for metric in scope_metrics.metrics:
                    rows.extend(
                        self._metric_rows(metric, service, res_json, scope, resource_metrics)
                    )
        self._insert(
            "INSERT INTO metrics (name, description, unit, type, timestamp, value, "
            "attributes, resource_attributes, resource_schema_url, scope_name, "
            "scope_version, scope_attributes, scope_schema_url, service_name, data) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        return len(rows)

    @staticmethod
    def _metric_rows(
        metric: Any, service: str, res_json: str, scope: Any, resource_metrics: Any
    ) -> list[tuple[Any, ...]]:
        kind = metric.WhichOneof("data")
        scope_cols = (
            scope.name or None,
            scope.version or None,
            json.dumps(_kv_to_dict(scope.attributes)),
            resource_metrics.schema_url or None,
            service,
        )
        rows: list[tuple[Any, ...]] = []
        if kind in ("gauge", "sum"):
            for point in getattr(metric, kind).data_points:
                value = point.as_double if point.HasField("as_double") else point.as_int
                rows.append(
                    (
                        metric.name,
                        metric.description or None,
                        metric.unit or None,
                        kind,
                        _ns_to_ms(point.time_unix_nano) if point.time_unix_nano else None,
                        float(value),
                        json.dumps(_kv_to_dict(point.attributes)),
                        res_json,
                        None,
                        *scope_cols,
                        None,
                    )
                )
        elif kind is not None:
            rows.append(
                (
                    metric.name,
                    metric.description or None,
                    metric.unit or None,
                    kind,
                    None,
                    None,
                    "{}",
                    res_json,
                    None,
                    *scope_cols,
                    json.dumps({"note": "complex metric stored as-is", "kind": kind}),
                )
            )
        return rows

    def _insert(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        if not rows:
            return
        with self._lock, self._connect() as conn:
            conn.executemany(sql, rows)
            conn.commit()


class _OTLPHandler(BaseHTTPRequestHandler):
    """Routes the three OTLP/HTTP signal paths to the shared :class:`TraceStore`."""

    store: TraceStore  # bound in serve()
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        """Silence the default per-request stderr logging; we log outcomes ourselves."""

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if self.headers.get("Content-Encoding") == "gzip":
            return gzip.decompress(body)
        return body

    def _respond(self, response: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        routes = {
            "/v1/traces": (
                ExportTraceServiceRequest,
                ExportTraceServiceResponse,
                self.store.write_spans,
            ),
            "/v1/logs": (
                ExportLogsServiceRequest,
                ExportLogsServiceResponse,
                self.store.write_logs,
            ),
            "/v1/metrics": (
                ExportMetricsServiceRequest,
                ExportMetricsServiceResponse,
                self.store.write_metrics,
            ),
        }
        route = routes.get(self.path)
        if route is None:
            self.send_error(404, f"unknown OTLP path {self.path}")
            return
        request_cls, response_cls, writer = route
        try:
            request = request_cls()
            request.ParseFromString(self._read_body())
            count = writer(request)
        except Exception:
            logger.exception("failed to persist OTLP payload for %s", self.path)
            self.send_error(500, "failed to persist OTLP payload")
            return
        logger.debug("persisted %d record(s) from %s", count, self.path)
        self._respond(response_cls().SerializeToString())


def serve(port: int = DEFAULT_PORT, db_path: Path | None = None) -> None:
    """Run the collector until interrupted, persisting to ``db_path``.

    Args:
        port: TCP port for the OTLP/HTTP listener (``4318`` by default).
        db_path: SQLite store to write; defaults to :data:`DEFAULT_DB_PATH`
            (overridable with the ``AITK_TRACES_DB`` environment variable).
    """
    resolved = db_path or Path(os.environ.get("AITK_TRACES_DB", DEFAULT_DB_PATH))
    handler = type("_BoundHandler", (_OTLPHandler,), {"store": TraceStore(resolved)})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    logger.info("OTLP collector listening on http://127.0.0.1:%d → %s", port, resolved)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


def main() -> None:
    """Console entrypoint: serve on ``PORT`` (default ``4318``)."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    serve(port=int(os.environ.get("PORT", DEFAULT_PORT)))


if __name__ == "__main__":
    main()
