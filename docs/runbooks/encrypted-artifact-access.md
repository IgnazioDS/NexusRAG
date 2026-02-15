# Encrypted Artifact Access

## Scope
Applies to DSAR exports, backup manifests, and other encrypted artifacts.

## Access Steps
1. Confirm admin authorization for the tenant.
2. Use the dedicated API endpoint (e.g. DSAR artifact download).
3. Validate audit trail entries for `crypto.decrypt.accessed`.

## Handling Guidance
- Do not copy decrypted payloads into logs or tickets.
- Store decrypted data in approved secure locations only.
