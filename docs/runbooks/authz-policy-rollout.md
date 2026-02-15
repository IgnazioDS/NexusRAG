# Authz Policy Rollout

## Purpose
- Provide a safe rollout checklist for introducing ABAC policies and document ACLs.

## Checklist
1. Apply the ABAC/ACL migration (`authorization_policies`, `document_permissions`, `document_labels`, `principal_attributes`) before enabling enforcement.
2. Backfill document ACLs for existing documents or keep `AUTHZ_ABAC_ENABLED=false` until policies are ready.
3. Confirm `AUTHZ_ABAC_ENABLED=true` and `AUTHZ_DEFAULT_DENY=true` in production config.
4. Inventory existing access patterns and define baseline allow policies per tenant.
5. Use `/v1/admin/authz/policies/{id}/simulate` to validate decisions before enabling.
6. Enable policies via `/v1/admin/authz/policies/{id}/enable` in small tenant batches.
7. Monitor audit events: `authz.policy.evaluate`, `authz.policy.denied`, `authz.access.denied`.
8. Validate document ACL coverage (owner grants on create, explicit grants for shared access).
9. Avoid wildcard-on-wildcard policies unless `AUTHZ_ALLOW_WILDCARDS=true` and explicitly approved.

## Escalation
- Engage security and platform owners if deny rates spike or critical tenants are blocked.
