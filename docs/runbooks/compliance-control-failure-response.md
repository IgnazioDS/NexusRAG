# Compliance Control Failure Response

## Purpose
- Provide guidance for investigating failed SOC 2 controls.

## Checklist
1. Identify failing control(s) from `/v1/admin/compliance/controls`.
2. Review latest evaluation details via `/v1/admin/compliance/evaluations?control_id=...`.
3. Confirm the underlying signal source (audit events, SLO snapshot, DR readiness).
4. Remediate root cause (e.g., resolve SLO breach, rotate keys, upload scan artifact).
5. Re-run evaluation on demand and confirm status transitions.

## Escalation
- If the control is critical and fails continuously, notify the security owner and track remediation.
