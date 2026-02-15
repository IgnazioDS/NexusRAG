# SCIM Provisioning Troubleshooting

## Purpose
- Guide operators through common SCIM provisioning failures.

## Checklist
1. Confirm `SCIM_ENABLED=true` and tenant entitlement `feature.identity.scim` are enabled.
2. Verify the SCIM bearer token status in `/v1/admin/identity/scim/token/*` (not revoked, not expired).
3. Check audit events for `identity.scim.user.*` or `identity.scim.group.updated` failures.
4. Validate SCIM payload schemas and required fields (`userName`, `displayName`).
5. Confirm group role bindings are configured in `scim_groups` if role mapping is expected.
6. Ensure the SCIM client is using `/v1/scim/v2` and correct pagination parameters.

## Escalation
- If provisioning remains blocked, involve identity admins and review IdP connector logs.
