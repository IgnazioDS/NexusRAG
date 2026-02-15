# Document Permission Operations

## Purpose
- Provide guidance for granting and revoking document ACLs safely.

## Checklist
1. List current permissions: `GET /v1/admin/authz/documents/{id}/permissions`.
2. Grant a permission: `POST /v1/admin/authz/documents/{id}/permissions`.
3. Bulk grant when onboarding a team: `POST /v1/admin/authz/documents/{id}/permissions/bulk`.
4. Revoke a permission: `DELETE /v1/admin/authz/documents/{id}/permissions/{perm_id}`.
5. Use `expires_at` for temporary access and verify expiration handling.
6. Confirm audit events: `authz.permission.granted` and `authz.permission.revoked`.
7. For shared access patterns, prefer group-based permissions when SCIM groups are configured.

## Escalation
- Escalate to governance owners if permission changes affect regulated documents.
