"""
Comprehensive end-to-end test script for the ShelfWise API.

Run with: .venv/Scripts/python.exe tests/test_api.py
(Requires a running server and DATABASE_URL; see README Testing section.)
"""

import os
import time
import sys
import uuid

import requests

BASE = "http://127.0.0.1:8000/api/v1"
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "references", "fast.csv")
TEST_EMAIL = f"test_{uuid.uuid4().hex[:8]}@shelfwise.com"
TEST_PASSWORD = "TestPass123"

# Test state
state = {}
passed = 0
failed = 0
errors = []


def _is_health_payload(body: dict) -> bool:
    return isinstance(body, dict) and "checks" in body and "database" in body.get("checks", {})


def _envelope_violation(expect_status: int, body: dict | None) -> str | None:
    """Return an error message if JSON body does not match API envelope rules."""
    if body is None or not isinstance(body, dict):
        return None
    if expect_status == 404:
        if body.get("status") != "error":
            return f'expected status "error" for 404, got {body.get("status")!r}'
        if "error" not in body or not isinstance(body["error"], dict):
            return 'expected top-level "error" object'
        return None
    if expect_status == 401:
        if body.get("status") != "error":
            return f'expected status "error" for 401, got {body.get("status")!r}'
        if "error" not in body or not isinstance(body["error"], dict):
            return 'expected top-level "error" object'
        return None
    if expect_status != 200:
        return None
    if _is_health_payload(body):
        if body.get("status") not in ("healthy", "degraded"):
            return f'expected health status healthy/degraded, got {body.get("status")!r}'
        return None
    if "data" in body or body.get("status") == "success":
        if body.get("status") != "success":
            return f'expected status "success", got {body.get("status")!r}'
    return None


def test(name, response, expect_status=200):
    global passed, failed
    ok_http = response.status_code == expect_status
    body = None
    try:
        body = response.json()
    except Exception:
        pass
    env_err = _envelope_violation(expect_status, body) if ok_http else None
    ok = ok_http and env_err is None

    status_icon = "PASS" if ok else "FAIL"
    print(f"  {status_icon} {name} -- HTTP {response.status_code}", end="")
    if not ok_http:
        print(f" (expected {expect_status})", end="")
        failed += 1
        detail = body.get("error", {}).get("message", "") if body else response.text[:200]
        errors.append(f"{name}: HTTP {response.status_code} -- {detail}")
    elif env_err:
        failed += 1
        errors.append(f"{name}: envelope -- {env_err}")
        print(f" (envelope: {env_err})", end="")
    else:
        passed += 1
    if body and body.get("message"):
        print(f" -- {body['message']}", end="")
    print()
    return ok, body


def auth_header():
    token = state.get("access_token")
    if not token:
        print("     [SKIP] No access token available")
        raise SystemExit(1)
    return {"Authorization": f"Bearer {token}"}


def main():
    global passed, failed

    print("=" * 60)
    print("ShelfWise API -- End-to-End Test Suite")
    print(f"Test email: {TEST_EMAIL}")
    print("=" * 60)

    # -- 1. Health Check
    print("\n1. Health Check")
    ok, body = test("GET /health", requests.get(f"{BASE}/health"))
    if ok:
        db_status = body.get("checks", {}).get("database", "unknown")
        print(f"     DB status: {db_status}")

    # -- 2. Auth: Register
    print("\n2. Auth: Register")
    ok, body = test("POST /auth/register", requests.post(f"{BASE}/auth/register", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
        "passwordConfirm": TEST_PASSWORD,
        "name": "Test Store",
    }))
    if ok:
        state["access_token"] = body["data"]["accessToken"]
        state["refresh_token"] = body["data"]["refreshToken"]

    # -- 3. Auth: Login
    print("\n3. Auth: Login")
    ok, body = test("POST /auth/login", requests.post(f"{BASE}/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
    }))
    if ok:
        state["access_token"] = body["data"]["accessToken"]
        state["refresh_token"] = body["data"]["refreshToken"]

    # -- 4. Auth: Login with wrong password (expect 401)
    print("\n4. Auth: Login with wrong password (expect 401)")
    test("POST /auth/login (bad password)", requests.post(f"{BASE}/auth/login", json={
        "email": TEST_EMAIL,
        "password": "WrongPassword999",
    }), expect_status=401)

    # -- 5. Auth: Me
    print("\n5. Auth: Me")
    ok, body = test("GET /auth/me", requests.get(f"{BASE}/auth/me", headers=auth_header()))
    if ok:
        state["user_id"] = body["data"]["id"]
        print(f"     User ID: {state['user_id']}")

    # -- 6. Auth: Refresh
    print("\n6. Auth: Refresh")
    ok, body = test("POST /auth/refresh", requests.post(f"{BASE}/auth/refresh", json={
        "refreshToken": state.get("refresh_token", ""),
    }))
    if ok:
        state["access_token"] = body["data"]["accessToken"]

    # ── 7. Upload: Step 1 -- Detect Columns ───────────────────
    print("\n7. Upload: Step 1 -- Detect Columns")
    with open(CSV_PATH, "rb") as f:
        ok, body = test("POST /upload/", requests.post(
            f"{BASE}/upload/",
            files={"file": ("fast.csv", f, "text/csv")},
            headers=auth_header(),
        ))
    if ok:
        data = body["data"]
        state["upload_session_id"] = data.get("uploadSessionId")
        print(f"     uploadSessionId: {state.get('upload_session_id', '')[:8]}...")
        print(f"     Columns detected: {data['columns']}")
        print(f"     Row count: {data['rowCount']}")
        print(f"     Suggested mappings:")
        for field, mapping in data.get("suggestedMapping", {}).items():
            print(f"       {field} -> {mapping['csvColumn']} (confidence: {mapping['confidence']})")
        print(f"     Unmapped columns: {data.get('unmappedCsvColumns', [])}")
        state["upload_suggestions"] = data

    # ── 7b. Upload: invalid session id ───────────────────────
    print("\n7b. Upload: Validate with bogus uploadSessionId (expect 404)")
    fake_id = str(uuid.uuid4())
    test(
        "POST /upload/validate (bad session)",
        requests.post(
            f"{BASE}/upload/validate",
            json={
                "uploadSessionId": fake_id,
                "columnMap": {
                    "date": "sale_date",
                    "product_id": "product_id",
                    "quantity_sold": "total_items_sold",
                },
            },
            headers=auth_header(),
        ),
        expect_status=404,
    )

    # ── 8. Upload: Step 2 -- Validate with Column Map ────────
    print("\n8. Upload: Step 2 -- Validate with Column Map")
    ok, body = test("POST /upload/validate", requests.post(
        f"{BASE}/upload/validate",
        json={
            "uploadSessionId": state.get("upload_session_id"),
            "columnMap": {
                "date": "sale_date",
                "product_id": "product_id",
                "quantity_sold": "total_items_sold",
            },
        },
        headers=auth_header(),
    ))
    if ok:
        data = body["data"]
        products = data.get("products", [])
        health = data.get("dataHealth", {})
        print(f"     Products found: {len(products)}")
        for p in products[:3]:
            print(f"       #{p['productId']}: {p['newRows']} rows ({p['action']})")
        if len(products) > 3:
            print(f"       ... and {len(products) - 3} more")
        print(f"     Data health: {health.get('overallScore', 'N/A')}/100 ({health.get('rating', 'N/A')})")
        qr = data.get("qualityReport", {})
        if qr.get("validationWarnings"):
            print(f"     Warnings: {qr['validationWarnings']}")

    # ── 9. Upload: Step 3 -- Confirm ─────────────────────────
    print("\n9. Upload: Step 3 -- Confirm")
    ok, body = test("POST /upload/confirm", requests.post(
        f"{BASE}/upload/confirm",
        json={
            "uploadSessionId": state.get("upload_session_id"),
            "skipProductIds": [],
        },
        headers=auth_header(),
    ))
    if ok:
        data = body["data"]
        print(f"     Products created: {data.get('productsCreated')}")
        print(f"     Rows inserted: {data.get('totalRowsInserted')}")

    # ── 10. Products: List ────────────────────────────────────
    print("\n10. Products: List")
    ok, body = test("GET /products/", requests.get(f"{BASE}/products/", headers=auth_header()))
    if ok:
        products = body["data"]
        if products:
            state["product_id"] = products[0]["id"]
            state["product_ext_id"] = products[0]["productId"]
            print(f"     First product: {products[0]['name']} (id={state['product_id'][:8]}...)")
            print(f"     Total products: {body['pagination']['totalItems']}")

    # ── 11. Products: Get Detail ─────────────────────────────
    print("\n11. Products: Get Detail")
    if state.get("product_id"):
        ok, body = test("GET /products/{id}", requests.get(
            f"{BASE}/products/{state['product_id']}", headers=auth_header(),
        ))

    # ── 11b. Products: Get non-existent (expect 404) ─────────
    print("\n11b. Products: Get non-existent (expect 404)")
    fake_product_id = str(uuid.uuid4())
    test("GET /products/{bogus} (404)", requests.get(
        f"{BASE}/products/{fake_product_id}", headers=auth_header(),
    ), expect_status=404)

    # ── 12. Products: Update ─────────────────────────────────
    print("\n12. Products: Update")
    if state.get("product_id"):
        ok, body = test("PATCH /products/{id}", requests.patch(
            f"{BASE}/products/{state['product_id']}",
            json={"category": "Beverages", "description": "Test product"},
            headers=auth_header(),
        ))

    # ── 13. Products: Archive & Unarchive ────────────────────
    print("\n13. Products: Archive")
    if state.get("product_id"):
        ok, body = test("PATCH /products/{id}/archive", requests.patch(
            f"{BASE}/products/{state['product_id']}/archive",
            headers=auth_header(),
        ))
        if ok:
            print(f"     isArchived: {body['data'].get('isArchived')}")

    print("\n13b. Products: Unarchive")
    if state.get("product_id"):
        ok, body = test("PATCH /products/{id}/archive (unarchive)", requests.patch(
            f"{BASE}/products/{state['product_id']}/archive",
            headers=auth_header(),
        ))
        if ok:
            is_archived = body["data"].get("isArchived")
            print(f"     isArchived: {is_archived}")
            if is_archived:
                failed += 1
                passed -= 1  # undo the pass from test()
                errors.append("Unarchive: expected isArchived=False but got True")

    # ── 14. Forecast: Generate ───────────────────────────────
    print("\n14. Forecast: Generate")
    if state.get("product_id"):
        ok, body = test("POST /forecasts/", requests.post(
            f"{BASE}/forecasts/",
            json={
                "productId": state["product_id"],
                "horizonDays": 30,
                "timeGranularity": "daily",
                "confidenceLevel": "95",
                "enableTuning": False,
            },
            headers=auth_header(),
        ))
        if ok:
            state["forecast_id"] = body["data"]["id"]
            print(f"     Forecast ID: {state['forecast_id'][:8]}...")
            print(f"     Status: {body['data']['status']}")

    # ── 15. Forecast: Poll for Completion ────────────────────
    print("\n15. Forecast: Poll for Completion")
    if state.get("forecast_id"):
        r = None
        for attempt in range(60):
            r = requests.get(
                f"{BASE}/forecasts/{state['forecast_id']}",
                headers=auth_header(),
            )
            if r.status_code == 200:
                status = r.json()["data"].get("status")
                if status in ("completed", "failed"):
                    print(f"     Final status: {status} (after {attempt + 1} polls)")
                    state["forecast_status"] = status
                    if status == "completed":
                        state["forecast_details"] = r.json()["data"]
                        mape = r.json()["data"].get("mape")
                        model = r.json()["data"].get("selectedModel")
                        print(f"     Model: {model}, MAPE: {mape}")
                    elif status == "failed":
                        print(f"     Error: {r.json()['data'].get('errorMessage')}")
                    break
                print(f"     ... status: {status} (attempt {attempt + 1})", end="\r")
            time.sleep(3)
        else:
            print("     WARN Timed out waiting for forecast completion")
            failed += 1
            errors.append("Forecast poll: timed out after 3 minutes")
        if r is not None:
            test("GET /forecasts/{id}", r)

    # ── 15b. Forecast: Get non-existent (expect 404) ─────────
    print("\n15b. Forecast: Get non-existent (expect 404)")
    fake_forecast_id = str(uuid.uuid4())
    test("GET /forecasts/{bogus} (404)", requests.get(
        f"{BASE}/forecasts/{fake_forecast_id}", headers=auth_header(),
    ), expect_status=404)

    # ── 16. Forecast: Results ────────────────────────────────
    print("\n16. Forecast: Results")
    if state.get("forecast_id") and state.get("forecast_status") == "completed":
        ok, body = test("GET /forecasts/{id}/results", requests.get(
            f"{BASE}/forecasts/{state['forecast_id']}/results",
            headers=auth_header(),
        ))
        if ok:
            results = body["data"]
            print(f"     Data points: {len(results)}")
            if results:
                print(f"     First: {results[0]['date']} -> {results[0]['predictedValue']}")
                print(f"     Last:  {results[-1]['date']} -> {results[-1]['predictedValue']}")

    # ── 17. Forecast: Components ─────────────────────────────
    print("\n17. Forecast: Components")
    if state.get("forecast_id") and state.get("forecast_status") == "completed":
        ok, body = test("GET /forecasts/{id}/components", requests.get(
            f"{BASE}/forecasts/{state['forecast_id']}/components",
            headers=auth_header(),
        ))
        if ok:
            data = body["data"]
            print(f"     Trend points: {len(data.get('trend', []))}")
            print(f"     Weekly effects: {len(data.get('weekly', []))}")
            print(f"     Yearly effects: {len(data.get('yearly', []))}")

    # ── 18. Forecast: List ───────────────────────────────────
    print("\n18. Forecast: List")
    ok, body = test("GET /forecasts/", requests.get(f"{BASE}/forecasts/", headers=auth_header()))
    if ok:
        print(f"     Total forecasts: {body['pagination']['totalItems']}")

    # ── 19. Export: CSV ──────────────────────────────────────
    print("\n19. Export: CSV")
    if state.get("forecast_id") and state.get("forecast_status") == "completed":
        r = requests.get(
            f"{BASE}/forecasts/{state['forecast_id']}/export/csv",
            headers=auth_header(),
        )
        ok = r.status_code == 200
        if ok:
            passed += 1
            print(f"  PASS GET /forecasts/{{id}}/export/csv -- {len(r.content)} bytes")
        else:
            failed += 1
            errors.append(f"Export CSV: HTTP {r.status_code}")
            print(f"  FAIL GET /forecasts/{{id}}/export/csv -- HTTP {r.status_code}")

    # ── 20. Export: Chart ─────────────────────────────────────
    print("\n20. Export: Chart")
    if state.get("forecast_id") and state.get("forecast_status") == "completed":
        r = requests.get(
            f"{BASE}/forecasts/{state['forecast_id']}/export/chart",
            headers=auth_header(),
        )
        ok = r.status_code == 200
        if ok:
            passed += 1
            print(f"  PASS GET /forecasts/{{id}}/export/chart -- {len(r.content)} bytes")
        else:
            failed += 1
            errors.append(f"Export Chart: HTTP {r.status_code}")
            print(f"  FAIL GET /forecasts/{{id}}/export/chart -- HTTP {r.status_code}")

    # ── 21. Export: PDF ───────────────────────────────────────
    print("\n21. Export: PDF")
    if state.get("forecast_id") and state.get("forecast_status") == "completed":
        r = requests.get(
            f"{BASE}/forecasts/{state['forecast_id']}/export/pdf",
            headers=auth_header(),
        )
        ok = r.status_code == 200
        if ok:
            passed += 1
            print(f"  PASS GET /forecasts/{{id}}/export/pdf -- {len(r.content)} bytes")
        else:
            failed += 1
            errors.append(f"Export PDF: HTTP {r.status_code}")
            print(f"  FAIL GET /forecasts/{{id}}/export/pdf -- HTTP {r.status_code}")

    # ── 22. Share: Create ─────────────────────────────────────
    print("\n22. Share: Create")
    if state.get("forecast_id") and state.get("forecast_status") == "completed":
        ok, body = test("POST /forecasts/{id}/share", requests.post(
            f"{BASE}/forecasts/{state['forecast_id']}/share",
            json={"expiresInHours": 24},
            headers=auth_header(),
        ))
        if ok:
            state["share_token"] = body["data"]["shareToken"]
            print(f"     Share token: {state['share_token']}")
            print(f"     Expires: {body['data'].get('expiresAt')}")

    # ── 23. Shared: View Public ──────────────────────────────
    print("\n23. Shared: View Public (no auth)")
    if state.get("share_token"):
        ok, body = test("GET /shared/forecasts/{token}", requests.get(
            f"{BASE}/shared/forecasts/{state['share_token']}",
        ))
        if ok:
            fc = body["data"]["forecast"]
            print(f"     Forecast status: {fc['status']}")
            print(f"     Results count: {len(body['data'].get('results', []))}")

    # ── 24. Share: Revoke ─────────────────────────────────────
    print("\n24. Share: Revoke")
    if state.get("forecast_id") and state.get("share_token"):
        ok, body = test("DELETE /forecasts/{id}/share", requests.delete(
            f"{BASE}/forecasts/{state['forecast_id']}/share",
            headers=auth_header(),
        ))

    # ── 24b. Shared: Revoked link returns 404 ────────────────
    print("\n24b. Shared: Revoked link (expect 404)")
    if state.get("share_token"):
        test("GET /shared/forecasts/{token} (revoked)", requests.get(
            f"{BASE}/shared/forecasts/{state['share_token']}",
        ), expect_status=404)

    # ── 24c. Chatbot: Send a message ─────────────────────────
    print("\n24c. Chatbot: Send a message")
    if state.get("forecast_id") and state.get("forecast_status") == "completed":
        ok, body = test("POST /forecasts/{id}/chat", requests.post(
            f"{BASE}/forecasts/{state['forecast_id']}/chat",
            json={"message": "Give me a brief summary of this forecast"},
            headers=auth_header(),
        ))
        if ok:
            state["chat_reply"] = body["data"]["reply"]
            print(f"     Reply: {body['data']['reply'][:100]}...")

    # ── 24d. Chatbot: Follow-up with history ─────────────────
    print("\n24d. Chatbot: Follow-up with history")
    if state.get("forecast_id") and state.get("chat_reply"):
        ok, body = test("POST /forecasts/{id}/chat (follow-up)", requests.post(
            f"{BASE}/forecasts/{state['forecast_id']}/chat",
            json={
                "message": "What are the main risks?",
                "history": [
                    {"role": "user", "content": "Give me a brief summary of this forecast"},
                    {"role": "assistant", "content": state["chat_reply"]},
                ],
            },
            headers=auth_header(),
        ))
        if ok:
            print(f"     Reply: {body['data']['reply'][:100]}...")

    # ── 24e. Chatbot: Non-existent forecast (expect 404) ─────
    print("\n24e. Chatbot: Non-existent forecast (expect 404)")
    fake_chat_id = str(uuid.uuid4())
    test("POST /forecasts/{bogus}/chat (404)", requests.post(
        f"{BASE}/forecasts/{fake_chat_id}/chat",
        json={"message": "Hello"},
        headers=auth_header(),
    ), expect_status=404)

    # ── 25. Dashboard ─────────────────────────────────────────
    print("\n25. Dashboard")
    ok, body = test("GET /dashboard/", requests.get(f"{BASE}/dashboard/", headers=auth_header()))
    if ok:
        qs = body["data"]["quickStats"]
        print(f"     Products: {qs['totalProducts']}, Forecasts: {qs['totalForecasts']}")
        print(f"     Avg MAPE: {qs.get('averageMape')}")

    # ── 26. Profile: Get ──────────────────────────────────────
    print("\n26. Profile: Get")
    ok, body = test("GET /profile/", requests.get(f"{BASE}/profile/", headers=auth_header()))

    # ── 27. Profile: Update ───────────────────────────────────
    print("\n27. Profile: Update")
    ok, body = test("PATCH /profile/", requests.patch(
        f"{BASE}/profile/",
        json={"name": "Updated Store", "defaultForecastPeriod": 6},
        headers=auth_header(),
    ))

    # ── 28. Profile: Change Password ──────────────────────────
    print("\n28. Profile: Change Password")
    ok, body = test("PUT /profile/password", requests.put(
        f"{BASE}/profile/password",
        json={"currentPassword": TEST_PASSWORD, "newPassword": "NewPass456"},
        headers=auth_header(),
    ))

    # ── 28b. Auth: Re-login with new password ─────────────────
    print("\n28b. Auth: Re-login with new password")
    ok, body = test("POST /auth/login (new password)", requests.post(f"{BASE}/auth/login", json={
        "email": TEST_EMAIL,
        "password": "NewPass456",
    }))
    if ok:
        state["access_token"] = body["data"]["accessToken"]
        state["refresh_token"] = body["data"]["refreshToken"]
        print("     Token refreshed with new password")

    # ── 29. Profile: Holidays ─────────────────────────────────
    print("\n29. Profile: Get Holidays")
    ok, body = test("GET /profile/holidays", requests.get(
        f"{BASE}/profile/holidays", headers=auth_header(),
    ))
    if ok:
        print(f"     Current calendar: {body['data']['holidayCalendar']}")

    print("\n30. Profile: Update Holidays")
    ok, body = test("PUT /profile/holidays", requests.put(
        f"{BASE}/profile/holidays",
        json={"holidayCalendar": "US"},
        headers=auth_header(),
    ))

    # ── 31. Upload: Download Template ─────────────────────────
    print("\n31. Upload: Download Template")
    r = requests.get(f"{BASE}/upload/template", headers=auth_header())
    if r.status_code == 200:
        passed += 1
        print(f"  PASS GET /upload/template -- {len(r.content)} bytes")
    else:
        failed += 1
        errors.append(f"Download Template: HTTP {r.status_code}")
        print(f"  FAIL GET /upload/template -- HTTP {r.status_code}")

    # ── 32. Auth: Logout (last step) ──────────────────────────
    print("\n32. Auth: Logout")
    ok, body = test("POST /auth/logout", requests.post(
        f"{BASE}/auth/logout", headers=auth_header(),
    ))

    # ── Summary ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed}/{total} failed")
    if errors:
        print("\nFailed tests:")
        for e in errors:
            print(f"  FAIL {e}")
    print("=" * 60)

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
