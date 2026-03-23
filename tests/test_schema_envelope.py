"""Unit tests for standardized API response helpers (no server or DB required)."""

import math

from app.schemas.common import paginated_response, success_response


def test_success_response_minimal():
    r = success_response({"accessToken": "a", "refreshToken": "b"})
    assert r == {"status": "success", "data": {"accessToken": "a", "refreshToken": "b"}}


def test_success_response_with_message():
    r = success_response({"id": "1"}, message="Done")
    assert r["status"] == "success"
    assert r["data"] == {"id": "1"}
    assert r["message"] == "Done"


def test_paginated_response_shape():
    r = paginated_response(
        data=[{"id": "x"}],
        page=2,
        limit=10,
        total_items=25,
    )
    assert r["status"] == "success"
    assert r["data"] == [{"id": "x"}]
    assert r["pagination"]["page"] == 2
    assert r["pagination"]["limit"] == 10
    assert r["pagination"]["totalItems"] == 25
    assert r["pagination"]["totalPages"] == math.ceil(25 / 10)


def test_paginated_response_empty_total_pages():
    r = paginated_response([], page=1, limit=20, total_items=0)
    assert r["pagination"]["totalPages"] == 0
