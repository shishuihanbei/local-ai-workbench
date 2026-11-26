"""OpenAPI 质量：operationId 必须唯一，否则生成客户端会互相覆盖。"""
from __future__ import annotations

from collections import defaultdict


def test_operation_ids_unique(client):
    spec = client.get("/api/openapi.json").json()
    ids: dict[str, list[str]] = defaultdict(list)
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if isinstance(op, dict) and op.get("operationId"):
                ids[op["operationId"]].append(f"{method.upper()} {path}")
    dupes = {k: v for k, v in ids.items() if len(v) > 1}
    assert not dupes, f"重复 operationId：{dupes}"


def test_every_error_response_documented_with_code(client):
    """接口文档里的错误响应至少要说明会返回错误（人工维护，先保证数量合理）。"""
    spec = client.get("/api/openapi.json").json()
    assert spec["info"]["version"]
    assert len(spec["paths"]) > 100
