"""The OpenAPI conformance oracle (Pillar 3): the target's spec is both the request GENERATOR (ground the
LLM on a real operation) and the response ORACLE (status + JSON-schema conformance, not `assert 200`)."""

from __future__ import annotations

from test_executor.oracle.openapi import (
    Operation,
    conformance_failures,
    fetch_spec,
    match_operation,
    operation_catalog,
    parse_operations,
)

__all__ = ["Operation", "conformance_failures", "fetch_spec", "match_operation",
           "operation_catalog", "parse_operations"]
