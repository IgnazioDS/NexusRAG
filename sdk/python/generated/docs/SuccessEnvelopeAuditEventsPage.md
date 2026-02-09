# SuccessEnvelopeAuditEventsPage


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**AuditEventsPage**](AuditEventsPage.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_audit_events_page import SuccessEnvelopeAuditEventsPage

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeAuditEventsPage from a JSON string
success_envelope_audit_events_page_instance = SuccessEnvelopeAuditEventsPage.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeAuditEventsPage.to_json())

# convert the object into a dict
success_envelope_audit_events_page_dict = success_envelope_audit_events_page_instance.to_dict()
# create an instance of SuccessEnvelopeAuditEventsPage from a dict
success_envelope_audit_events_page_from_dict = SuccessEnvelopeAuditEventsPage.from_dict(success_envelope_audit_events_page_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


