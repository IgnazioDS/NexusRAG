# Authz Deny Debugging

## Purpose
- Diagnose `AUTHZ_DENIED` responses for document and corpus access.

## Checklist
1. Capture the `request_id` from the client response headers.
2. Review audit events for `authz.access.denied` and `authz.policy.denied` matching the `request_id`.
3. Confirm the caller has a valid role and tenant scope (RBAC must pass first).
4. Check document ACLs via `/v1/admin/authz/documents/{id}/permissions` for missing or expired grants.
5. Verify ABAC policies and priorities; deny policies always override allow policies.
6. Run `/v1/admin/authz/policies/{id}/simulate` with the same principal/resource context.
7. Confirm `AUTHZ_ADMIN_BYPASS_DOCUMENT_ACL=false` unless explicitly required.

## Escalation
- Escalate to security owners if deny responses are unexpected or widespread.
