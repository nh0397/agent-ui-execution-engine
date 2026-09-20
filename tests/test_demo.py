import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from demo.app import create_app


def csrf(client):
    # The edit UI exposes only the synthetic session's form token.
    return re.search(r'name="csrf" value="([^"]+)"', client.get("/customers/C-104/edit").text)[1]


def draft(client, postal="12345"):
    token = csrf(client)
    response = client.post("/customers/C-104/review", data={"csrf": token, "street": "41 Example Avenue", "city": "Sampletown", "postal": postal})
    return token, response


def test_save_is_idempotent_and_verifies_database(tmp_path):
    path = tmp_path / "demo.db"
    with TestClient(create_app(path)) as client:
        token, review = draft(client)
        assert "Review address change" in review.text
        first = client.post("/save", data={"csrf": token})
        second = client.post("/save", data={"csrf": token})
        assert first.url == second.url
        assert "Address updated" in first.text
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT revision,street FROM customers WHERE id='C-104'").fetchone() == (1, "41 Example Avenue")
        assert conn.execute("SELECT count(*) FROM updates").fetchone()[0] == 1


def test_invalid_input_does_not_write(tmp_path):
    path = tmp_path / "demo.db"
    with TestClient(create_app(path)) as client:
        _, response = draft(client, "oops")
        assert "Invalid address" in response.text
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM updates").fetchone()[0] == 0


def test_csrf_rejected(tmp_path):
    with TestClient(create_app(tmp_path / "demo.db")) as client:
        assert "Permission denied" in client.post("/save", data={"csrf": "invalid"}).text


def test_concurrent_change_is_not_overwritten(tmp_path):
    path = tmp_path / "demo.db"
    with TestClient(create_app(path)) as client:
        token, _ = draft(client)
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE customers SET revision=revision+1 WHERE id='C-104'")
        assert "Record changed during review" in client.post("/save", data={"csrf": token}).text


@pytest.mark.parametrize("scenario,text", [("normal", "Customer not found"), ("session-expired", "Session expired"), ("transient", "Temporary load failure")])
def test_exception_states(tmp_path, scenario, text):
    with TestClient(create_app(tmp_path / "demo.db", scenario)) as client:
        assert text in client.get("/customers?customer_id=C-999").text


def test_uncertain_save_has_committed_and_can_be_reconciled(tmp_path):
    with TestClient(create_app(tmp_path / "demo.db", "uncertain-save")) as client:
        token, _ = draft(client)
        interrupted = client.post("/save", data={"csrf": token})
        assert "Save result uncertain" in interrupted.text
        path = re.search(r'href="(/confirmation/[^"]+)"', interrupted.text)[1]
        assert "Address updated" in client.get(path).text
