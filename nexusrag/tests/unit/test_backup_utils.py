from __future__ import annotations

import json
from pathlib import Path

from nexusrag.core.config import get_settings
from nexusrag.services import backup as backup_service


def test_manifest_signature_roundtrip(monkeypatch) -> None:
    # Ensure manifest signing and verification remain stable.
    monkeypatch.setenv("BACKUP_SIGNING_KEY", "test-signing-key")
    get_settings.cache_clear()
    manifest = backup_service.BackupManifest(
        backup_id="1",
        created_at="2026-02-10T00:00:00+00:00",
        backup_type="all",
        app_version="test",
        manifest_version="1.0",
        encryption_enabled=False,
        signing_enabled=True,
        components=[],
    )
    signature = backup_service.sign_manifest(manifest, b"test-signing-key")
    assert backup_service.verify_signature(manifest, signature, b"test-signing-key")
    get_settings.cache_clear()


def test_validate_manifest_reports_missing_artifact(tmp_path: Path) -> None:
    # Flag missing artifacts so restore validation fails deterministically.
    manifest = backup_service.BackupManifest(
        backup_id="2",
        created_at="2026-02-10T00:00:00+00:00",
        backup_type="metadata",
        app_version="test",
        manifest_version="1.0",
        encryption_enabled=False,
        signing_enabled=False,
        components=[
            backup_service.BackupArtifact(
                name="metadata",
                path="metadata_snapshot.json.gz",
                sha256="deadbeef",
                size_bytes=10,
                encrypted=False,
            )
        ],
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    errors = backup_service.validate_manifest(manifest_path, require_signature=False)
    assert any("missing artifact" in error for error in errors)


def test_restore_dry_run_allows_destructive_without_flag(tmp_path: Path, monkeypatch) -> None:
    # Allow dry-run validation without destructive confirmation.
    monkeypatch.setenv("RESTORE_REQUIRE_SIGNATURE", "false")
    get_settings.cache_clear()

    artifact_path = tmp_path / "db_full.sql.gz"
    artifact_path.write_bytes(b"test")
    checksum = backup_service._sha256_file(artifact_path)
    manifest = backup_service.BackupManifest(
        backup_id="3",
        created_at="2026-02-10T00:00:00+00:00",
        backup_type="full",
        app_version="test",
        manifest_version="1.0",
        encryption_enabled=False,
        signing_enabled=False,
        components=[
            backup_service.BackupArtifact(
                name="db_full",
                path=artifact_path.name,
                sha256=checksum,
                size_bytes=artifact_path.stat().st_size,
                encrypted=False,
            )
        ],
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    report = backup_service.restore_from_manifest(
        manifest_path=manifest_path,
        components=["db"],
        target_db_url="postgresql://example",
        dry_run=True,
        allow_destructive=False,
    )
    assert report.status == "passed"
    get_settings.cache_clear()
