"""Shared test helpers."""

import os

ADMIN_EMAIL = "shared_admin@test.com"
ADMIN_PASSWORD = "adminpass123"
_SETUP_TOKEN = os.environ.get("SETUP_TOKEN", "")


def get_admin_headers(test_client):
    """Ensure a superadmin exists and return auth headers for it."""
    test_client.post(
        "/api/setup",
        json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
            "first_name": "Shared",
            "last_name": "Admin",
        },
        headers={"X-Setup-Token": _SETUP_TOKEN},
    )
    resp = test_client.post("/api/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if resp.status_code != 200:
        raise RuntimeError(f"Admin login failed: {resp.status_code} - {resp.json()}")
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def get_admin_id(test_client, admin_headers):
    """Return the id of the shared superadmin user."""
    resp = test_client.get("/api/admin/users", params={"role": "admin"}, headers=admin_headers)
    for user in resp.json():
        if user["email"] == ADMIN_EMAIL:
            return user["id"]
    raise RuntimeError("Superadmin not found via /admin/users")


def create_approved_user(
    test_client,
    admin_headers,
    email,
    password="validpass123",
    first_name="Test",
    last_name="User",
):
    """Register a user and approve them via admin. Returns JWT token."""
    reg = test_client.post(
        "/api/register/guardian",
        json={
            "email": email,
            "password": password,
            "first_name": first_name,
            "last_name": last_name,
        },
    )
    user_id = reg.json()["id"]
    test_client.patch(
        f"/api/admin/users/{user_id}/status",
        json={"status": "approved"},
        headers=admin_headers,
    )
    login_resp = test_client.post("/api/login", json={"email": email, "password": password})
    if login_resp.status_code != 200:
        raise RuntimeError(f"Login failed: {login_resp.status_code} - {login_resp.json()}")
    return login_resp.json()["token"]
