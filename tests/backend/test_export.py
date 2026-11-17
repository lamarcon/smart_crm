"""CSV export: permission, read scope, filters and safe cells."""

from __future__ import annotations

import csv
import io
from copy import deepcopy
from dataclasses import replace

from app.services.export import export_csv
from app.services.workspace import project_workspace_state
from test_account_access_api import (  # noqa: F401 - fixtures
    ADMIN_PASSWORD,
    ORIGIN,
    LiveStack,
    _seed_member,
    _workspace_version,
    live_stack,
)
from test_account_access_service import (  # noqa: F401 - fixtures
    account_access_database_url,
    recovery_control_database,
)
from test_permission_workspace import state
from test_workspace_authorization import principal


def rows(body: bytes) -> list[list[str]]:
    assert body.startswith("﻿".encode("utf-8"))
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig")), delimiter=";"))


def test_export_has_titles_names_and_only_what_the_user_sees() -> None:
    seller = principal("Vendedor")
    body, count = export_csv(project_workspace_state(state(), seller), "leads", None, "pt-BR")
    table = rows(body)
    assert table[0][:3] == ["Identificador", "Nome completo", "Empresa"]
    assert {row[0] for row in table[1:]} == {"L-seller", "L-seller-assist"}
    assert count == 2
    responsible = table[0].index("Responsável")
    assert {row[responsible] for row in table[1:]} == {"Seller", "Other"}


def test_export_follows_the_listed_ids_and_skips_name_only_records() -> None:
    seller = replace(principal("Vendedor"), permissions=(("companies", "read", "own"),))
    projected = project_workspace_state(state(), seller)
    body, count = export_csv(projected, "companies", None, "pt-BR")
    assert [row[0] for row in rows(body)[1:]] == ["E-1"] and count == 1  # E-2 is only a linked name
    body, count = export_csv(projected, "leads", ["L-seller", "L-hidden"], "pt-BR")
    assert [row[0] for row in rows(body)[1:]] == ["L-seller"] and count == 1


def test_export_titles_follow_the_language_and_cells_cannot_run_formulas() -> None:
    data = state().model_dump(by_alias=True)
    data["products"][0]["name"] = "=HYPERLINK(\"http://x\")"
    data["products"][0]["active"] = False
    data["customFieldSchemas"]["products"] = [{"key": "ncm", "label": "NCM", "type": "text"}]
    data["products"][0]["customFields"] = {"ncm": "+8471"}
    from app.schemas import WorkspaceState

    body, _count = export_csv(WorkspaceState.model_validate(data), "products", None, "en")
    table = rows(body)
    assert table[0][:2] == ["Identifier", "Product name"]
    assert table[0][-1] == "NCM"
    assert table[1][1] == "'=HYPERLINK(\"http://x\")"
    assert table[1][table[0].index("Status")] == "Inactive"
    assert table[1][-1] == "'+8471"


# --- Endpoint ---------------------------------------------------------------------------

def _login(live_stack: LiveStack, role: str) -> dict[str, str]:  # noqa: F811
    _user_id, email = _seed_member(live_stack.database_url, role=role)
    return live_stack.admin(live_stack.login(email, ADMIN_PASSWORD))


def test_export_endpoint_needs_the_export_permission(live_stack: LiveStack) -> None:  # noqa: F811
    _workspace_version(live_stack.database_url, initialize_at=1)
    admin = _login(live_stack, "Administrador")
    seller = _login(live_stack, "Vendedor")

    answer = live_stack.client.post("/api/export/contacts", headers=admin, json={})
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"] == "text/csv; charset=utf-8"
    assert answer.headers["content-disposition"].startswith('attachment; filename="smart-crm-contacts-')
    assert answer.headers["cache-control"] == "no-store"
    assert rows(answer.content)[0][0] == "Identificador"

    assert live_stack.client.post("/api/export/contacts", headers=seller, json={}).status_code == 403
    assert live_stack.client.post("/api/export/quotes", headers=admin, json={}).status_code == 404
    foreign = {"origin": "https://evil.test", "cookie": admin["cookie"]}
    assert live_stack.client.post("/api/export/contacts", headers=foreign, json={}).status_code == 403

    roles = deepcopy(live_stack.client.get("/api/permissions", headers=admin).json()["roles"])
    roles["Vendedor"]["contacts"]["export"] = "all"
    assert live_stack.client.put("/api/permissions", headers=admin, json={"roles": roles}).status_code == 200
    allowed = live_stack.client.post("/api/export/contacts", headers={**seller, "accept-language": "en"}, json={"ids": []})
    assert allowed.status_code == 200, allowed.text
    assert rows(allowed.content) == [rows(allowed.content)[0]]
    assert rows(allowed.content)[0][0] == "Identifier"
