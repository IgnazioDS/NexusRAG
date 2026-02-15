from __future__ import annotations

from nexusrag.services.auth.scim import ScimUserInput, apply_active_status, apply_scim_user_patch


def test_scim_patch_active_false_disables_user() -> None:
    # Ensure SCIM active=false drives disabled status semantics.
    current = ScimUserInput(
        external_id="ext-1",
        user_name="user-1",
        email="user@example.com",
        display_name="User",
        active=True,
        groups=None,
    )
    payload = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "path": "active", "value": False}],
    }
    updated = apply_scim_user_patch(payload=payload, current=current)
    assert updated.active is False
    assert apply_active_status(updated.active) == "disabled"
