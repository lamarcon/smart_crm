"""Permission matrix API: only the Administrador reads and changes it; it applies at once."""

from __future__ import annotations

from copy import deepcopy

from test_account_access_api import (  # noqa: F401 - fixtures
    ADMIN_PASSWORD,
    ORIGIN,
    LiveStack,
    _seed_member,
    live_stack,
)
from test_account_access_service import (  # noqa: F401 - fixtures
    account_access_database_url,
    recovery_control_database,
)


def _admin(live_stack: LiveStack) -> dict[str, str]:  # noqa: F811
    _admin_id, email = _seed_member(live_stack.database_url, role="Administrador")
    return live_stack.admin(live_stack.login(email, ADMIN_PASSWORD))


def _member(live_stack: LiveStack, role: str) -> dict[str, str]:  # noqa: F811
    _user_id, email = _seed_member(live_stack.database_url, role=role)
    return live_stack.admin(live_stack.login(email, ADMIN_PASSWORD))


def test_session_carries_the_default_permissions_of_the_role(live_stack: LiveStack) -> None:  # noqa: F811
    seller = _member(live_stack, "Vendedor")
    session = live_stack.client.get("/api/auth/session", headers=seller).json()
    assert session["permissions"]["deals"] == {
        "read": "own", "create": "all", "update": "own", "delete": "own", "import": "none", "export": "none",
    }
    assert session["permissions"]["products"]["update"] == "none"
    admin = _admin(live_stack)
    assert live_stack.client.get("/api/auth/session", headers=admin).json()["permissions"]["leads"]["export"] == "all"


def test_administrator_reads_and_saves_the_matrix_and_it_applies_on_the_next_request(live_stack: LiveStack) -> None:  # noqa: F811
    admin = _admin(live_stack)
    seller = _member(live_stack, "Vendedor")

    current = live_stack.client.get("/api/permissions", headers=admin)
    assert current.status_code == 200, current.text
    assert current.headers["cache-control"] == "no-store"
    body = current.json()
    assert list(body["roles"]) == ["Gestor", "Vendedor", "Assistente", "Faturamento"]
    assert body["roles"] == body["defaults"]
    assert body["administrator"]["deals"]["delete"] == "all"
    assert body["options"]["contacts"]["read"] == ["none", "all"]
    assert body["options"]["deals"]["read"] == ["none", "own", "team", "all"]

    roles = deepcopy(body["roles"])
    roles["Vendedor"]["deals"]["delete"] = "none"
    roles["Vendedor"]["leads"]["read"] = "team"
    roles["Vendedor"]["contacts"]["export"] = "all"
    saved = live_stack.client.put("/api/permissions", headers=admin, json={"roles": roles})
    assert saved.status_code == 200, saved.text
    assert saved.json()["roles"]["Vendedor"]["deals"]["delete"] == "none"
    assert saved.json()["defaults"]["Vendedor"]["deals"]["delete"] == "own"

    session = live_stack.client.get("/api/auth/session", headers=seller).json()
    assert session["permissions"]["deals"]["delete"] == "none"
    assert session["permissions"]["leads"]["read"] == "team"
    assert session["permissions"]["contacts"]["export"] == "all"
    assert live_stack.client.get("/api/permissions", headers=admin).json()["roles"] == saved.json()["roles"]


def test_invalid_matrices_are_rejected_without_changes(live_stack: LiveStack) -> None:  # noqa: F811
    admin = _admin(live_stack)
    roles = live_stack.client.get("/api/permissions", headers=admin).json()["roles"]

    broken = deepcopy(roles)
    broken["Vendedor"]["contacts"]["read"] = "own"  # contacts have no owner
    answer = live_stack.client.put("/api/permissions", headers=admin, json={"roles": broken})
    assert answer.status_code == 422
    assert answer.json()["error"] == {
        "code": "validation_error", "message": "Permissões inválidas.", "field": "roles.Vendedor.contacts.read",
    }

    with_admin = {**deepcopy(roles), "Administrador": deepcopy(roles["Gestor"])}
    assert live_stack.client.put("/api/permissions", headers=admin, json={"roles": with_admin}).status_code == 422
    missing = deepcopy(roles)
    del missing["Faturamento"]["deals"]["export"]
    assert live_stack.client.put("/api/permissions", headers=admin, json={"roles": missing}).status_code == 422
    unknown = deepcopy(roles)
    unknown["Gestor"]["deals"]["read"] = "everyone"
    english = live_stack.client.put("/api/permissions", headers={**admin, "accept-language": "en"}, json={"roles": unknown})
    assert english.json()["error"]["message"] == "Invalid permissions."

    assert live_stack.client.get("/api/permissions", headers=admin).json()["roles"] == roles


def test_only_the_administrator_reaches_the_matrix(live_stack: LiveStack) -> None:  # noqa: F811
    admin = _admin(live_stack)
    roles = live_stack.client.get("/api/permissions", headers=admin).json()["roles"]
    manager = _member(live_stack, "Gestor")

    assert live_stack.client.get("/api/permissions", headers=manager).status_code == 403
    assert live_stack.client.put("/api/permissions", headers=manager, json={"roles": roles}).status_code == 403
    foreign = {"origin": "https://evil.test", "cookie": admin["cookie"]}
    assert live_stack.client.put("/api/permissions", headers=foreign, json={"roles": roles}).status_code == 403
    live_stack.client.cookies.clear()
    assert live_stack.client.get("/api/permissions", headers={"origin": ORIGIN}).status_code == 401
