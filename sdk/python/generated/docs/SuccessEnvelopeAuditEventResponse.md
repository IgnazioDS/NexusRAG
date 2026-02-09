# SuccessEnvelopeAuditEventResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**AuditEventResponse**](AuditEventResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_audit_event_response import SuccessEnvelopeAuditEventResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeAuditEventResponse from a JSON string
success_envelope_audit_event_response_instance = SuccessEnvelopeAuditEventResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeAuditEventResponse.to_json())

# convert the object into a dict
success_envelope_audit_event_response_dict = success_envelope_audit_event_response_instance.to_dict()
# create an instance of SuccessEnvelopeAuditEventResponse from a dict
success_envelope_audit_event_response_from_dict = SuccessEnvelopeAuditEventResponse.from_dict(success_envelope_audit_event_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


