"""Shared test helpers."""

ADMIN_EMAIL = "shared_admin@test.com"
ADMIN_PASSWORD = "adminpass123"


def get_admin_headers(test_client):
    """Ensure a superadmin exists and return auth headers for it."""
    test_client.post("/setup", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    resp = test_client.post("/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_approved_user(test_client, admin_headers, email, password="validpass123"):
    """Register a user and approve them via admin. Returns JWT token."""
    test_client.post("/register", json={"email": email, "password": password})
    test_client.patch(
        f"/admin/users/{email}/status",
        json={"status": "aprovado"},
        headers=admin_headers,
    )
    login_resp = test_client.post("/login", json={"email": email, "password": password})
    return login_resp.json()["access_token"]
