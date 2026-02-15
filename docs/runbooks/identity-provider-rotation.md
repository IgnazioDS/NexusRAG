# Identity Provider Rotation

## Purpose
- Rotate identity provider client secrets and SCIM tokens safely.

## Checklist
1. Create a new client secret in the IdP or secret manager.
2. Update the provider with `/v1/admin/identity/providers/{id}/rotate-secret-ref`.
3. If rotating SCIM tokens:
   - Create a new token via `/v1/admin/identity/scim/token/create`.
   - Update the IdP SCIM connector to use the new token.
   - Revoke the old token via `/v1/admin/identity/scim/token/revoke`.
4. Validate new SSO and SCIM flows using a test tenant user.
5. Monitor audit events for `identity.provider.updated` and `identity.scim.token.*`.

## Escalation
- If rotations cause outages, roll back to the previous secret ref or token and notify security.
