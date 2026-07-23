"""The local OTLP→sqlite collector maps OTLP protobuf into the AI Toolkit store.

These tests exercise :class:`TraceStore` directly with hand-built OTLP protobuf
messages — no socket, no live exporter — and read the rows back to confirm the
exact encoding the AI Toolkit viewer expects: base64 ids, millisecond times,
flattened attributes, and ``service.name`` resolution.
"""

import base64
import json
import sqlite3

import pytest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import (
    AnyValue,
    ArrayValue,
    KeyValue,
    KeyValueList,
)
from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord, ResourceLogs, ScopeLogs
from opentelemetry.proto.metrics.v1.metrics_pb2 import (
    Gauge,
    Histogram,
    HistogramDataPoint,
    Metric,
    NumberDataPoint,
    ResourceMetrics,
    ScopeMetrics,
)
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span, Status

from foundry_agent.otel_collector import TraceStore, _anyvalue_to_native

_TRACE_ID = bytes(range(16))
_SPAN_ID = bytes(range(8))
_PARENT_ID = bytes(range(8, 16))


@pytest.fixture
def store(tmp_path):
    """A TraceStore over a throwaway db; the schema is created on construction."""
    return TraceStore(tmp_path / "traces.db")


def _kv(key: str, value: AnyValue) -> KeyValue:
    return KeyValue(key=key, value=value)


def _service_resource(name: str):
    from opentelemetry.proto.resource.v1.resource_pb2 import Resource

    return Resource(attributes=[_kv("service.name", AnyValue(string_value=name))])


def _rows(db_path, table):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("any_value", "expected"),
    [
        (AnyValue(string_value="hi"), "hi"),
        (AnyValue(bool_value=True), True),
        (AnyValue(int_value=7), 7),
        (AnyValue(double_value=1.5), 1.5),
        (AnyValue(array_value=ArrayValue(values=[AnyValue(int_value=1)])), [1]),
        (
            AnyValue(kvlist_value=KeyValueList(values=[_kv("k", AnyValue(string_value="v"))])),
            {"k": "v"},
        ),
        (AnyValue(bytes_value=b"\x00\x01"), base64.b64encode(b"\x00\x01").decode()),
    ],
)
def test_anyvalue_unwraps_each_variant(any_value, expected):
    assert _anyvalue_to_native(any_value) == expected


def test_span_is_mapped_with_the_stores_encoding(store):
    span = Span(
        trace_id=_TRACE_ID,
        span_id=_SPAN_ID,
        parent_span_id=_PARENT_ID,
        name="workflow.run",
        kind=Span.SPAN_KIND_INTERNAL,
        start_time_unix_nano=1_700_000_000_000_000_000,
        end_time_unix_nano=1_700_000_000_005_000_000,  # +5 ms
        attributes=[_kv("workflow.name", AnyValue(string_value="policy-report-agent"))],
        status=Status(code=Status.STATUS_CODE_OK, message="done"),
    )
    request = ExportTraceServiceRequest(
        resource_spans=[
            ResourceSpans(
                resource=_service_resource("policy-report-agent"),
                scope_spans=[ScopeSpans(spans=[span])],
            )
        ]
    )

    assert store.write_spans(request) == 1
    (row,) = _rows(store._db_path, "spans")

    assert row["trace_id"] == base64.b64encode(_TRACE_ID).decode()
    assert row["span_id"] == base64.b64encode(_SPAN_ID).decode()
    assert row["parent_span_id"] == base64.b64encode(_PARENT_ID).decode()
    assert row["service_name"] == "policy-report-agent"
    assert row["kind"] == Span.SPAN_KIND_INTERNAL
    assert row["start_time"] == 1_700_000_000_000  # ns → ms
    assert row["end_time"] == 1_700_000_000_005
    assert row["duration"] == 5
    assert json.loads(row["attributes"]) == {"workflow.name": "policy-report-agent"}
    assert row["status_code"] == Status.STATUS_CODE_OK
    assert row["status_message"] == "done"


def test_span_events_and_links_are_persisted_as_json(store):
    span = Span(
        trace_id=_TRACE_ID,
        span_id=_SPAN_ID,
        name="chat",
        start_time_unix_nano=1_000_000,
        end_time_unix_nano=2_000_000,
        events=[
            Span.Event(
                name="gen_ai.content.prompt",
                time_unix_nano=1_500_000,
                attributes=[_kv("content", AnyValue(string_value="secret payload"))],
            )
        ],
        links=[Span.Link(trace_id=_TRACE_ID, span_id=_PARENT_ID)],
    )
    request = ExportTraceServiceRequest(
        resource_spans=[
            ResourceSpans(resource=_service_resource("svc"), scope_spans=[ScopeSpans(spans=[span])])
        ]
    )

    store.write_spans(request)
    (row,) = _rows(store._db_path, "spans")

    (event,) = json.loads(row["events"])
    assert event["name"] == "gen_ai.content.prompt"
    assert event["timestamp"] == 1  # ns → ms
    assert event["attributes"] == {"content": "secret payload"}
    (link,) = json.loads(row["span_links"])
    assert link["span_id"] == base64.b64encode(_PARENT_ID).decode()


def test_parentless_span_stores_null_parent_and_falls_back_service_name(store):
    span = Span(
        trace_id=_TRACE_ID,
        span_id=_SPAN_ID,
        name="root",
        start_time_unix_nano=1_000_000,
        end_time_unix_nano=1_000_000,
    )
    request = ExportTraceServiceRequest(
        resource_spans=[ResourceSpans(scope_spans=[ScopeSpans(spans=[span])])]
    )

    store.write_spans(request)
    (row,) = _rows(store._db_path, "spans")

    assert row["parent_span_id"] is None
    assert row["service_name"] == "unknown_service"


def test_log_record_body_and_severity_are_persisted(store):
    record = LogRecord(
        time_unix_nano=5_000_000,
        severity_number=9,
        severity_text="INFO",
        body=AnyValue(string_value="hello log"),
        attributes=[_kv("gen_ai.system", AnyValue(string_value="openai"))],
    )
    request = ExportLogsServiceRequest(
        resource_logs=[
            ResourceLogs(
                resource=_service_resource("svc"),
                scope_logs=[ScopeLogs(log_records=[record])],
            )
        ]
    )

    assert store.write_logs(request) == 1
    (row,) = _rows(store._db_path, "logs")

    assert json.loads(row["body"]) == "hello log"
    assert row["timestamp"] == 5  # ns → ms
    assert row["severity_text"] == "INFO"
    assert row["service_name"] == "svc"


def test_gauge_and_sum_metrics_become_scalar_value_rows(store):
    request = ExportMetricsServiceRequest(
        resource_metrics=[
            ResourceMetrics(
                resource=_service_resource("svc"),
                scope_metrics=[
                    ScopeMetrics(
                        metrics=[
                            Metric(
                                name="tokens",
                                unit="1",
                                gauge=Gauge(
                                    data_points=[
                                        NumberDataPoint(time_unix_nano=3_000_000, as_int=42)
                                    ]
                                ),
                            )
                        ]
                    )
                ],
            )
        ]
    )

    assert store.write_metrics(request) == 1
    (row,) = _rows(store._db_path, "metrics")

    assert row["name"] == "tokens"
    assert row["type"] == "gauge"
    assert row["value"] == 42.0
    assert row["timestamp"] == 3
    assert row["data"] is None


def test_histogram_metric_is_stored_as_data_blob(store):
    request = ExportMetricsServiceRequest(
        resource_metrics=[
            ResourceMetrics(
                resource=_service_resource("svc"),
                scope_metrics=[
                    ScopeMetrics(
                        metrics=[
                            Metric(
                                name="latency",
                                histogram=Histogram(
                                    data_points=[HistogramDataPoint(count=3, sum=1.0)]
                                ),
                            )
                        ]
                    )
                ],
            )
        ]
    )

    store.write_metrics(request)
    (row,) = _rows(store._db_path, "metrics")

    assert row["type"] == "histogram"
    assert row["value"] is None
    assert json.loads(row["data"])["kind"] == "histogram"


def test_empty_request_writes_nothing(store):
    assert store.write_spans(ExportTraceServiceRequest()) == 0
    assert _rows(store._db_path, "spans") == []
