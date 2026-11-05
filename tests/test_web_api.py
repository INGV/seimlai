"""API contract checks with temporary workspaces; never execute seismic jobs."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from seimlai.gui.services.catalog_watcher import EarthquakeItem
from seimlai.web.app import create_app


ROOT = Path(__file__).resolve().parents[1]


class WebAPITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.previous_cwd = Path.cwd()
        self.addCleanup(os.chdir, self.previous_cwd)
        self.root = Path(self.temp.name)
        (self.root / "user_configuration").mkdir()
        self.path = self.root / "user_configuration/config.yaml"
        self.path.write_bytes((ROOT / "user_configuration/config.default.yaml").read_bytes())
        os.chdir(self.root)
        # Polling is exercised separately by the existing watcher; keep API tests deterministic.
        self.watch = patch("seimlai.web.app.CatalogWatcher.start_watching")
        self.watch.start()
        self.addCleanup(self.watch.stop)
        self.app = create_app(str(self.path))
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def config(self):
        return self.client.get("/api/config").json()

    def test_config_save_preserves_comments_and_rejects_stale_edit(self):
        current = self.config()
        current["data"]["model"]["p_threshold"] = 0.6
        saved = self.client.put("/api/config", json=current)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertIn("#threshold decision for P-wave", self.path.read_text())
        self.assertEqual(saved.json()["data"]["model"]["p_threshold"], 0.6)
        self.assertNotEqual(saved.json()["version"], current["version"])
        self.assertEqual(self.client.put("/api/config", json=current).status_code, 409)

    def test_invalid_config_does_not_change_disk_or_memory(self):
        current = self.config()
        previous = self.path.read_bytes()
        for mutate in (
            lambda data: data["geography"].update(minlatitude=95),
            lambda data: data["model"].update(p_threshold=1.5),
            lambda data: data["model"].update(batch_size="oops"),
            lambda data: data.pop("dates"),
        ):
            request = copy.deepcopy(current)
            mutate(request["data"])
            response = self.client.put("/api/config", json=request)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(self.path.read_bytes(), previous)
            self.assertEqual(self.app.state.config.data, current["data"])

    def test_pipeline_modes_and_busy_guard(self):
        version = self.config()["version"]
        with patch.object(self.app.state.pipeline, "run_workflow_async", return_value=True) as run:
            self.assertEqual(self.client.post("/api/pipeline/run", json={"mode": "continue", "version": version}).status_code, 200)
            self.assertEqual(run.call_args.kwargs["from_step"], "04")
            self.client.post("/api/pipeline/run", json={"mode": "single", "step": "03", "version": version})
            self.assertEqual(run.call_args.kwargs["only_steps"], ["03"])
            self.assertEqual(self.client.post("/api/pipeline/run", json={"version": "stale"}).status_code, 409)
            self.assertEqual(run.call_count, 2)
        self.assertEqual(self.client.post("/api/pipeline/run", json={"mode": "utility", "command": "anything", "version": version}).status_code, 422)
        self.assertEqual(self.client.post("/api/pipeline/run", json={"step": "99", "version": version}).status_code, 422)
        current = self.config()
        self.app.state.pipeline.is_running = True
        self.assertEqual(self.client.post("/api/pipeline/run", json={"version": version}).status_code, 409)
        self.assertEqual(self.client.put("/api/config", json=current).status_code, 409)
        self.app.state.pipeline.is_running = False

    def test_catalog_selection_is_per_request_and_json_has_no_nan(self):
        watcher = self.app.state.watcher
        watcher.catalogs["hypodd"] = [EarthquakeItem("1", 42.5, 13.1, 7.2, float("nan"), None, "hypodd")]
        response = self.client.get("/api/catalogs/hypodd")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["events"][0]["magnitude"])
        self.assertEqual(watcher.active_source, "gamma")
        self.assertEqual(self.client.get("/api/catalogs/gamma").json()["events"], [])

    def test_model_file_versioning_and_backup(self):
        path = "/api/files/hypoellipse/grad.mod"
        current = self.client.get(path).json()
        current["content"] = "model one\n"
        result = self.client.put(path, json=current)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.put(path, json=current).status_code, 409)
        next_update = result.json()
        next_update["content"] = "model two\n"
        self.assertEqual(self.client.put(path, json=next_update).status_code, 200)
        self.assertEqual((self.path.parent / "hypoellipse/grad.mod.bak").read_text(), "model one\n")
        self.assertEqual(self.client.get("/api/files/unknown/file").status_code, 404)
        self.assertEqual(self.client.get("/api/files/hypodd/.hidden").status_code, 404)

    def test_case_selection_and_dirty_version(self):
        current = self.config()
        target = self.root / "case_studies/other"
        target.mkdir(parents=True)
        response = self.client.post("/api/cases/select", json={"path": str(target), "version": current["version"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["case_study"]["name"], "other")
        self.assertTrue((target / ".seimlai-config.yaml").exists())
        self.assertEqual(self.client.post("/api/cases/select", json={"path": str(self.root), "version": response.json()["version"]}).status_code, 404)

    def test_websocket_and_cross_origin_write(self):
        with self.client.websocket_connect("/api/live") as socket:
            message = socket.receive_json()
            self.assertEqual(len(message["steps"]), 5)
            self.assertFalse(message["running"])
            json.dumps(message, allow_nan=False)
        response = self.client.post("/api/pipeline/stop", headers={"origin": "https://unrelated.example"})
        self.assertEqual(response.status_code, 403)

    def test_static_frontend_deep_links_do_not_hide_missing_api_routes(self):
        dist = self.root / "frontend/dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "cesium").mkdir()
        (dist / "index.html").write_text("<html>SeiMLAI frontend</html>")
        (dist / "cesium/worker.js").write_text("// Cesium worker")
        with TestClient(create_app(str(self.path), frontend_dir=dist)) as client:
            self.assertIn("SeiMLAI frontend", client.get("/app").text)
            self.assertEqual(client.get("/cesium/worker.js").status_code, 200)
            self.assertEqual(client.get("/api/not-an-endpoint").status_code, 404)


if __name__ == "__main__":
    unittest.main()
