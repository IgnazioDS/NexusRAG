# Incident Management

## Scope
Use this runbook for automated incidents created from alert rules and runtime shed/degrade hooks.

## Lifecycle
1. List open incidents: `GET /v1/admin/incidents?status=open`.
2. Acknowledge ownership: `POST /v1/admin/incidents/{id}/ack`.
3. Assign responder: `POST /v1/admin/incidents/{id}/assign`.
4. Review timeline: `GET /v1/admin/incidents/{id}/timeline`.
5. Resolve when mitigated: `POST /v1/admin/incidents/{id}/resolve`.

## Notes
- Incident dedupe key is tenant/category/rule scoped; repeated alerts append timeline events.
- `incident.opened|acknowledged|assigned|resolved` audit events are required evidence artifacts.
