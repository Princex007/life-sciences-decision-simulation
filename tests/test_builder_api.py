import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import uvicorn

from app import api
from app.main import app
from app.services.simulation_builder import SimulationBuilderService


def test_builder_http_crud_validation_run_and_tree(tmp_path, monkeypatch):
    project = Path(__file__).resolve().parents[1]
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setattr(api.routes, "builder", SimulationBuilderService(tmp_path, project / "examples"))
    api.routes._results.clear()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"

    def request(path, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(base + path, data=data, method=method,
            headers={"Content-Type": "application/json"} if data is not None else {})
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            if not raw:
                parsed = None
            elif "application/json" in response.headers.get("Content-Type", ""):
                parsed = json.loads(raw)
            else:
                parsed = raw.decode()
            return response.status, parsed

    try:
        for _ in range(100):
            try:
                status, page = request("/")
                assert status == 200 and "Simulation Builder" in page
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.05)
        else:
            raise AssertionError("FastAPI server did not start")

        # Read from tests/fixtures rather than the example picker: this is the only definition whose
        # scenario policy branches four ways, which is what the tree assertions below check.
        definition = json.loads((project / "tests" / "fixtures" / "market_pricing_competition.json")
                                .read_text(encoding="utf-8"))
        status, created = request("/simulations", "POST", definition)
        assert status == 201
        simulation_id = created["simulation_id"]
        assert request(f"/simulations/{simulation_id}/validate", "POST")[1]["valid"]
        saved = request(f"/simulations/{simulation_id}")[1]["definition"]
        saved["metadata"]["description"] = "Edited through the API"
        assert request(f"/simulations/{simulation_id}", "PUT", saved)[0] == 200
        assert request(f"/simulations/{simulation_id}")[1]["definition"]["metadata"]["description"] == "Edited through the API"

        invalid = json.loads(json.dumps(saved))
        invalid["action_definitions"][0]["agent_id"] = "missing-agent"
        with pytest.raises(urllib.error.HTTPError) as caught:
            request("/simulations/validate", "POST", invalid)
        assert caught.value.code == 422
        assert b"unknown agent missing-agent" in caught.value.read()

        run = request(f"/simulations/{simulation_id}/run", "POST")[1]
        assert run["scenario_count"] == 4
        assert len(request(f"/simulations/{simulation_id}/results")[1]["scenarios"]) == 4
        tree = request(f"/simulations/{simulation_id}/tree")[1]
        assert tree["root"]["node_type"] == "root"
        assert len(tree["root"]["children"][0]["children"]) == 2
        saved = request(f"/simulations/{simulation_id}")[1]["definition"]
        saved["settings"]["decision_policy"] = "llm"
        assert request(f"/simulations/{simulation_id}", "PUT", saved)[0] == 200
        with pytest.raises(urllib.error.HTTPError) as missing_key:
            request(f"/simulations/{simulation_id}/run", "POST")
        assert missing_key.value.code == 422
        assert b"LLM_API_KEY" in missing_key.value.read()
        duplicate = request(f"/simulations/{simulation_id}/duplicate", "POST")[1]["simulation_id"]
        assert request(f"/simulations/{duplicate}")[0] == 200
        assert request(f"/simulations/{duplicate}", "DELETE")[0] == 204
        # The UI's Discard relies on the deleted id vanishing from both the list and the record.
        assert duplicate not in [item["simulation_id"] for item in request("/simulations")[1]]
        with pytest.raises(urllib.error.HTTPError) as gone:
            request(f"/simulations/{duplicate}")
        assert gone.value.code == 404
        assert request(f"/simulations/{simulation_id}", "DELETE")[0] == 204
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        api.routes._results.clear()
