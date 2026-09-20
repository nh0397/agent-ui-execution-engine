"""Protocol checks only; these do not demonstrate a human takeover."""
import re

import httpx

from engine.operator import OperatorBridge


def test_operator_commands_require_origin_and_token():
    bridge = OperatorBridge(0)
    try:
        origin = f"http://127.0.0.1:{bridge.port}"
        with httpx.Client(base_url=origin, trust_env=False) as client:
            page = client.get("/")
            assert page.status_code == 200
            assert page.headers["cache-control"] == "no-store"
            token = re.search("const token='([^']+)'", page.text)[1]
            assert client.post("/command", json={"kind": "resume"}).status_code == 403
            assert client.post("/command", headers={"Origin": "http://other.invalid", "X-Operator-Token": token}, json={"kind": "resume"}).status_code == 403
            assert bridge.commands.empty()
            response = client.post("/command", headers={"Origin": origin, "X-Operator-Token": token}, json={"kind": "resume"})
            assert response.status_code == 202
            assert bridge.commands.get_nowait() == {"kind": "resume"}
            assert client.get("/", headers={"Host": "other.invalid"}).status_code == 403
    finally:
        bridge.close()
