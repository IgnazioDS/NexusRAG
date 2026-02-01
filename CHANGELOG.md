# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

- None.

## 0.1.6 - 2026-02-01

- Enforced pgvector extension via migration for consistent environments.
- Corrected cosine retrieval with similarity scoring and deterministic ordering.
- Added embedding dimension invariants and controlled retrieval errors.
- Expanded tests for embeddings and retrieval invariants.

## 0.1.5 - 2026-02-01

- Hardened DB session lifecycle and explicit transaction boundaries for `/run`.
- Race-safe session upsert with tenant mismatch handling.
- Improved DB error mapping and persistence boundary tests.

## 0.1.4 - 2026-02-01

- Hardened SSE framing and headers.
- Added request_id tracing to all SSE events.
- Improved graceful error and disconnect handling.
- Expanded SSE integration tests.

## 0.1.3 - 2026-02-01

- Added deterministic seed script for demo corpus and chunks.
- Updated README seeding instructions and sanity check.

## 0.1.2 - 2026-02-01

- Add validation checklist commands and clarify release process language.
- Remove obsolete docker compose version field to avoid warnings.

## 0.1.1 - 2026-02-01

- Add release scaffolding, changelog, and documented release process.
