# SSO Incident Response

## Purpose
- Provide a repeatable checklist for investigating SSO login failures.

## Checklist
1. Confirm `SSO_ENABLED=true` and tenant entitlement `feature.identity.sso` are enabled.
2. Validate the IdP configuration in `/v1/admin/identity/providers` (issuer, client_id, URLs, enabled).
3. Check Redis availability for state/nonce storage (state/nonce TTLs are required).
4. Review audit events for `identity.sso.login.failure` and correlate `request_id`.
5. Verify the IdP JWKS endpoint is reachable and the signing key matches the token `kid`.
6. Ensure callback URLs are HTTPS in non-dev environments and are registered with the IdP.
7. If JIT is expected, confirm `feature.identity.jit` entitlement and `jit_enabled=true` on the provider.

## Escalation
- Escalate to identity/security owners if failures persist or impact multiple tenants.
