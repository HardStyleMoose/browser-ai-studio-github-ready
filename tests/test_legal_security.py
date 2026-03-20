from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from automation.n8n_sidecar import N8nSidecarManager, PINNED_N8N_VERSION
from automation.provider_hub import ProviderCatalogService, validate_endpoint_profile_config
from core.legal_docs import LEGAL_DOC_FILENAMES, legal_doc_manifest
from core.security_utils import redact_sensitive_text
from installer.build_support import create_release_payload
from installer.install_utils import verify_release_payload, write_install_manifest


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


class LegalSecurityTests(unittest.TestCase):
    def test_required_legal_files_exist(self):
        manifest = legal_doc_manifest()
        for key in LEGAL_DOC_FILENAMES:
            self.assertIn(key, manifest)
            self.assertTrue(manifest[key]["exists"], key)
            self.assertTrue(manifest[key]["version"], key)
        readme_text = (_project_root() / "README.md").read_text(encoding="utf-8")
        self.assertIn("LICENSE.md", readme_text)
        self.assertIn("EULA.md", readme_text)
        self.assertIn("SECURITY.md", readme_text)

    def test_release_payload_manifest_includes_hashes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            app_dist_dir = temp_path / "dist_app"
            legal_docs_dir = app_dist_dir / "legal_docs"
            legal_docs_dir.mkdir(parents=True, exist_ok=True)
            (app_dist_dir / "BrowserAI_Lab.exe").write_bytes(b"demo-exe")
            for key, filename in LEGAL_DOC_FILENAMES.items():
                if key == "contributing":
                    continue
                source = _project_root() / filename
                if source.exists():
                    (legal_docs_dir / filename).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            payload_zip = temp_path / "app_payload.zip"
            manifest_path = temp_path / "release_manifest.json"
            manifest = create_release_payload(app_dist_dir, payload_zip, manifest_path)
            self.assertTrue(payload_zip.exists())
            self.assertEqual(manifest["payload_sha256"], json.loads(manifest_path.read_text(encoding="utf-8"))["payload_sha256"])
            self.assertTrue(manifest["eula_sha256"])
            self.assertTrue(manifest["notice_sha256"])
            self.assertTrue(manifest["eula_version"])

    def test_payload_verification_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            app_dist_dir = temp_path / "dist_app"
            legal_docs_dir = app_dist_dir / "legal_docs"
            legal_docs_dir.mkdir(parents=True, exist_ok=True)
            (app_dist_dir / "BrowserAI_Lab.exe").write_bytes(b"demo-exe")
            for name in ["EULA.md", "NOTICE.md"]:
                source = _project_root() / name
                (legal_docs_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            payload_zip = temp_path / "app_payload.zip"
            manifest_path = temp_path / "release_manifest.json"
            manifest = create_release_payload(app_dist_dir, payload_zip, manifest_path)
            self.assertEqual(manifest["payload_sha256"], verify_release_payload(payload_zip, manifest))
            with open(payload_zip, "ab") as handle:
                handle.write(b"tampered")
            with self.assertRaises(RuntimeError):
                verify_release_payload(payload_zip, manifest)

    def test_install_manifest_records_legal_acceptance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            app_executable = temp_path / "BrowserAI_Lab.exe"
            app_executable.write_bytes(b"exe")
            manifest_path = write_install_manifest(
                temp_path,
                {"entry_executable": app_executable.name, "payload_sha256": "abc123"},
                app_executable,
                [],
                legal_acceptance={
                    "accepted_at": "2026-03-20 12:00:00",
                    "eula_version": "2026-03-20",
                    "payload_sha256": "abc123",
                },
            )
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("2026-03-20", payload["legal_acceptance"]["eula_version"])
            self.assertEqual("abc123", payload["legal_acceptance"]["payload_sha256"])

    def test_provider_profiles_store_env_var_names_only_and_validate_urls(self):
        valid = validate_endpoint_profile_config(
            {
                "base_url": "https://api.example.com/v1",
                "api_key_env_var": "BROWSERAI_PROVIDER_API_KEY",
            }
        )
        self.assertTrue(valid["ok"])

        invalid_http = validate_endpoint_profile_config(
            {
                "base_url": "http://api.example.com/v1",
                "api_key_env_var": "BROWSERAI_PROVIDER_API_KEY",
            }
        )
        self.assertFalse(invalid_http["ok"])

        invalid_secret = validate_endpoint_profile_config(
            {
                "base_url": "https://api.example.com/v1",
                "api_key_env_var": "sk-secret-value-1234567890",
            }
        )
        self.assertFalse(invalid_secret["ok"])

        with tempfile.TemporaryDirectory() as temp_dir:
            service = ProviderCatalogService(temp_dir)
            service.save_endpoint_profiles(
                [
                    {
                        "label": "Test",
                        "base_url": "https://api.example.com/v1",
                        "api_key_env_var": "sk-secret-value-1234567890",
                        "enabled": True,
                    }
                ]
            )
            raw = service.profile_path.read_text(encoding="utf-8")
            self.assertNotIn("sk-secret-value-1234567890", raw)
            loaded = service.load_endpoint_profiles()
            self.assertEqual("", loaded[0]["api_key_env_var"])

    def test_security_redaction_masks_secret_like_values(self):
        redacted = redact_sensitive_text(
            "Authorization: Bearer sk-secret-token api_key=abcdef1234567890 TOKEN=mytokenvalue"
        )
        self.assertNotIn("sk-secret-token", redacted)
        self.assertNotIn("abcdef1234567890", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_n8n_settings_stay_local_and_pinned(self):
        self.assertRegex(PINNED_N8N_VERSION, r"^\d+\.\d+\.\d+$")
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = N8nSidecarManager(temp_dir)
            manager.apply_settings(
                {
                    "port": 7788,
                    "editor_url": "https://evil.example.com",
                    "api_key_env_var": "n8n_api_key",
                }
            )
            state = manager.collect_state()
            self.assertEqual("http://localhost:7788", state["editor_url"])
            self.assertEqual("N8N_API_KEY", state["api_key_env_var"])

    def test_github_security_configs_exist(self):
        root = _project_root()
        self.assertTrue((root / ".github" / "dependabot.yml").exists())
        self.assertTrue((root / ".github" / "workflows" / "security.yml").exists())
        self.assertTrue((root / ".github" / "workflows" / "codeql.yml").exists())


if __name__ == "__main__":
    unittest.main()
