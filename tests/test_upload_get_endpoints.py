"""
Tests for Upload Session GET Endpoints.

Tests the two new GET endpoints:
  - GET /api/v1/upload/{session_id}           -- Re-fetch session metadata
  - GET /api/v1/upload/{session_id}/validation -- Re-fetch validation result

Run with: .venv/Scripts/python.exe tests/test_upload_get_endpoints.py
(Requires a running server and DATABASE_URL; see README Testing section.)
"""

import os
import sys
import uuid

import requests

BASE = "http://127.0.0.1:8000/api/v1"
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "references", "fast.csv")
TEST_EMAIL = f"test_upload_get_{uuid.uuid4().hex[:8]}@shelfwise.com"
TEST_PASSWORD = "TestPass123"

# Test state
state = {}
passed = 0
failed = 0
errors = []


def test(name, response, expect_status=200):
    global passed, failed
    ok_http = response.status_code == expect_status
    body = None
    try:
        body = response.json()
    except Exception:
        pass

    ok = ok_http
    status_icon = "PASS" if ok else "FAIL"
    print(f"  {status_icon} {name} -- HTTP {response.status_code}", end="")
    if not ok_http:
        print(f" (expected {expect_status})", end="")
        failed += 1
        detail = body.get("error", {}).get("message", "") if body else response.text[:200]
        errors.append(f"{name}: HTTP {response.status_code} (expected {expect_status}) -- {detail}")
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
    print("Upload Session GET Endpoints -- Test Suite")
    print(f"Test email: {TEST_EMAIL}")
    print("=" * 60)

    # -- Setup: Register a test user
    print("\n1. Setup: Register test user")
    ok, body = test("POST /auth/register", requests.post(f"{BASE}/auth/register", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
        "passwordConfirm": TEST_PASSWORD,
        "name": "Upload GET Test Store",
    }))
    if ok:
        state["access_token"] = body["data"]["accessToken"]
        state["refresh_token"] = body["data"]["refreshToken"]

    # -- 2. Upload CSV (Step 1) -- sets up session for GET tests
    print("\n2. Upload CSV (Step 1)")
    with open(CSV_PATH, "rb") as f:
        ok, body = test("POST /upload/", requests.post(
            f"{BASE}/upload/",
            files={"file": ("fast.csv", f, "text/csv")},
            headers=auth_header(),
        ))
    if ok:
        data = body["data"]
        state["upload_session_id"] = data.get("uploadSessionId")
        state["upload_response"] = data
        print(f"     uploadSessionId: {state.get('upload_session_id', '')[:8]}...")
        print(f"     Columns: {data['columns']}")
        print(f"     Row count: {data['rowCount']}")
        print(f"     Status: {data.get('status')}")

        # Verify status field is present in POST response
        if data.get("status") != "uploaded":
            failed += 1
            passed -= 1
            errors.append(f"POST /upload/ response missing status='uploaded', got: {data.get('status')}")
            print(f"     FAIL: Expected status='uploaded', got '{data.get('status')}'")

    # -- 3. GET /upload/{session_id} -- Re-fetch session metadata
    print("\n3. GET /upload/{session_id} -- Session metadata")
    if state.get("upload_session_id"):
        ok, body = test("GET /upload/{session_id}", requests.get(
            f"{BASE}/upload/{state['upload_session_id']}",
            headers=auth_header(),
        ))
        if ok:
            data = body["data"]
            print(f"     uploadSessionId: {data['uploadSessionId'][:8]}...")
            print(f"     Columns: {data['columns']}")
            print(f"     Row count: {data['rowCount']}")
            print(f"     Filename: {data['fileName']}")
            print(f"     File size: {data['fileSizeMb']} MB")
            print(f"     Status: {data['status']}")
            print(f"     Suggested mapping keys: {list(data.get('suggestedMapping', {}).keys())}")
            print(f"     Confidence keys: {list(data.get('confidence', {}).keys())}")
            print(f"     columnMap: {data.get('columnMap')}")

            # Verify all expected fields are present
            expected_fields = ["uploadSessionId", "columns", "rowCount", "fileName", "fileSizeMb", "suggestedMapping", "confidence", "columnMap", "status"]
            missing = [f for f in expected_fields if f not in data]
            if missing:
                failed += 1
                passed -= 1
                errors.append(f"GET /upload/{{session_id}} missing fields: {missing}")
                print(f"     FAIL: Missing fields: {missing}")
            else:
                print("     All expected fields present [OK]")

            # columnMap must be null when status == "uploaded"
            if data.get("columnMap") is not None:
                failed += 1
                passed -= 1
                errors.append(f"columnMap should be null when status='uploaded', got: {data['columnMap']}")
                print(f"     FAIL: columnMap should be null when status='uploaded'")
            else:
                print("     columnMap is null (status=uploaded) [OK]")

            # Verify data matches the POST response
            post_data = state.get("upload_response", {})
            if data["columns"] != post_data.get("columns"):
                failed += 1
                passed -= 1
                errors.append("GET response columns don't match POST response")
                print("     FAIL: Columns mismatch")
            if data["rowCount"] != post_data.get("rowCount"):
                failed += 1
                passed -= 1
                errors.append("GET response rowCount doesn't match POST response")
                print("     FAIL: rowCount mismatch")
            if data["status"] != "uploaded":
                failed += 1
                passed -= 1
                errors.append(f"GET response status should be 'uploaded', got '{data['status']}'")
                print(f"     FAIL: Status should be 'uploaded', got '{data['status']}'")

    # -- 4. GET /upload/{session_id} with bogus ID (expect 404)
    print("\n4. GET /upload/{session_id} -- Non-existent session (expect 404)")
    fake_id = str(uuid.uuid4())
    ok, body = test("GET /upload/{bogus} (404)", requests.get(
        f"{BASE}/upload/{fake_id}",
        headers=auth_header(),
    ), expect_status=404)
    if ok:
        print(f"     Error code: {body.get('error', {}).get('code')}")

    # -- 5. GET /upload/{session_id}/validation BEFORE validation (expect 404)
    print("\n5. GET /upload/{session_id}/validation -- Before validate (expect 404)")
    if state.get("upload_session_id"):
        ok, body = test("GET /upload/{session_id}/validation (before validate)", requests.get(
            f"{BASE}/upload/{state['upload_session_id']}/validation",
            headers=auth_header(),
        ), expect_status=404)
        if ok:
            error_msg = body.get("error", {}).get("message", "")
            print(f"     Error message: {error_msg}")
            if "not been run" not in error_msg.lower() and "not found" not in error_msg.lower():
                failed += 1
                passed -= 1
                errors.append(f"Expected 'validation not run' message, got: {error_msg}")

    # -- 6. Validate (Step 2) -- sets up validation result
    print("\n6. Validate (Step 2)")
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
        state["validation_response"] = data
        products = data.get("products", [])
        print(f"     Products found: {len(products)}")
        print(f"     Has suspicious: {data.get('hasSuspicious')}")

    # -- 7. GET /upload/{session_id} AFTER validation -- status should be "validated"
    print("\n7. GET /upload/{session_id} -- After validation (status=validated)")
    if state.get("upload_session_id"):
        ok, body = test("GET /upload/{session_id} (after validate)", requests.get(
            f"{BASE}/upload/{state['upload_session_id']}",
            headers=auth_header(),
        ))
        if ok:
            data = body["data"]
            print(f"     Status: {data['status']}")
            print(f"     columnMap: {data.get('columnMap')}")
            if data["status"] != "validated":
                failed += 1
                passed -= 1
                errors.append(f"GET session status should be 'validated' after validate, got '{data['status']}'")
                print(f"     FAIL: Expected status='validated'")
            else:
                print("     Status correctly updated to 'validated' [OK]")

            # columnMap should be the mapping sent to POST /validate
            expected_map = {
                "date": "sale_date",
                "product_id": "product_id",
                "quantity_sold": "total_items_sold",
            }
            if data.get("columnMap") != expected_map:
                failed += 1
                passed -= 1
                errors.append(f"columnMap after validate expected {expected_map}, got: {data.get('columnMap')}")
                print(f"     FAIL: columnMap mismatch")
            else:
                print("     columnMap matches validated mapping [OK]")

    # -- 8. GET /upload/{session_id}/validation -- Re-fetch validation result
    print("\n8. GET /upload/{session_id}/validation -- Validation result")
    if state.get("upload_session_id"):
        ok, body = test("GET /upload/{session_id}/validation", requests.get(
            f"{BASE}/upload/{state['upload_session_id']}/validation",
            headers=auth_header(),
        ))
        if ok:
            data = body["data"]
            print(f"     Products: {len(data.get('products', []))}")
            print(f"     Has suspicious: {data.get('hasSuspicious')}")
            print(f"     Quality report present: {'qualityReport' in data}")
            print(f"     Data health present: {'dataHealth' in data}")

            # Verify expected fields
            expected_fields = ["products", "hasSuspicious", "qualityReport", "dataHealth"]
            missing = [f for f in expected_fields if f not in data]
            if missing:
                failed += 1
                passed -= 1
                errors.append(f"GET /upload/{{session_id}}/validation missing fields: {missing}")
                print(f"     FAIL: Missing fields: {missing}")
            else:
                print("     All expected fields present [OK]")

            # Verify data matches the POST /validate response
            post_val = state.get("validation_response", {})
            if len(data.get("products", [])) != len(post_val.get("products", [])):
                failed += 1
                passed -= 1
                errors.append("GET validation products count doesn't match POST validate response")
                print("     FAIL: Products count mismatch")
            else:
                print("     Products count matches POST /validate response [OK]")

    # -- 9. GET /upload/{session_id}/validation with bogus ID (expect 404)
    print("\n9. GET /upload/{session_id}/validation -- Non-existent session (expect 404)")
    fake_id = str(uuid.uuid4())
    ok, body = test("GET /upload/{bogus}/validation (404)", requests.get(
        f"{BASE}/upload/{fake_id}/validation",
        headers=auth_header(),
    ), expect_status=404)

    # -- 10. Cross-user access test: second user can't access first user's session
    print("\n10. Cross-user access test")
    second_email = f"test_upload_get2_{uuid.uuid4().hex[:8]}@shelfwise.com"
    ok, body = test("POST /auth/register (second user)", requests.post(f"{BASE}/auth/register", json={
        "email": second_email,
        "password": TEST_PASSWORD,
        "passwordConfirm": TEST_PASSWORD,
        "name": "Second User",
    }))
    if ok and state.get("upload_session_id"):
        second_token = body["data"]["accessToken"]
        second_header = {"Authorization": f"Bearer {second_token}"}

        ok2, body2 = test("GET /upload/{session_id} (wrong user -> 404)", requests.get(
            f"{BASE}/upload/{state['upload_session_id']}",
            headers=second_header,
        ), expect_status=404)
        if ok2:
            print("     Cross-user access correctly blocked [OK]")

        ok3, body3 = test("GET /upload/{session_id}/validation (wrong user -> 404)", requests.get(
            f"{BASE}/upload/{state['upload_session_id']}/validation",
            headers=second_header,
        ), expect_status=404)
        if ok3:
            print("     Cross-user validation access correctly blocked [OK]")

    # -- 11. Unauthenticated access (expect 401)
    print("\n11. Unauthenticated access (expect 401)")
    if state.get("upload_session_id"):
        test("GET /upload/{session_id} (no auth -> 401)", requests.get(
            f"{BASE}/upload/{state['upload_session_id']}",
        ), expect_status=401)

        test("GET /upload/{session_id}/validation (no auth -> 401)", requests.get(
            f"{BASE}/upload/{state['upload_session_id']}/validation",
        ), expect_status=401)

    # -- 12. Confirm upload (Step 3) -- session gets deleted
    print("\n12. Confirm upload (Step 3)")
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

    # -- 13. GET endpoints after confirm (session deleted -> expect 404)
    print("\n13. GET endpoints after confirm (session deleted -> expect 404)")
    if state.get("upload_session_id"):
        test("GET /upload/{session_id} (after confirm -> 404)", requests.get(
            f"{BASE}/upload/{state['upload_session_id']}",
            headers=auth_header(),
        ), expect_status=404)

        test("GET /upload/{session_id}/validation (after confirm -> 404)", requests.get(
            f"{BASE}/upload/{state['upload_session_id']}/validation",
            headers=auth_header(),
        ), expect_status=404)

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
