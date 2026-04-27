"""Shared test helpers."""

ADMIN_EMAIL = "shared_admin@test.com"
ADMIN_PASSWORD = "adminpass123"


def get_admin_headers(test_client):
    """Ensure a superadmin exists and return auth headers for it."""
    test_client.post("/setup", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    resp = test_client.post("/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def get_admin_id(test_client, admin_headers):
    """Return the id of the shared superadmin user."""
    resp = test_client.get(
        "/admin/users", params={"role": "admin"}, headers=admin_headers
    )
    for user in resp.json():
        if user["email"] == ADMIN_EMAIL:
            return user["id"]
    raise RuntimeError("Superadmin not found via /admin/users")


def create_approved_user(test_client, admin_headers, email, password="validpass123", name="Test"):
    """Register a user and approve them via admin. Returns JWT token."""
    reg = test_client.post(
        "/register/responsavel", json={"email": email, "password": password, "name": name}
    )
    user_id = reg.json()["id"]
    test_client.patch(
        f"/admin/users/{user_id}/status",
        json={"status": "aprovado"},
        headers=admin_headers,
    )
    login_resp = test_client.post("/login", json={"email": email, "password": password})
    return login_resp.json()["token"]
