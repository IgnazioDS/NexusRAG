# AuditEventResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **int** |  | 
**occurred_at** | **str** |  | 
**tenant_id** | **str** |  | 
**actor_type** | **str** |  | 
**actor_id** | **str** |  | 
**actor_role** | **str** |  | 
**event_type** | **str** |  | 
**outcome** | **str** |  | 
**resource_type** | **str** |  | 
**resource_id** | **str** |  | 
**request_id** | **str** |  | 
**ip_address** | **str** |  | 
**user_agent** | **str** |  | 
**metadata_json** | **Dict[str, object]** |  | 
**error_code** | **str** |  | 
**created_at** | **str** |  | 

## Example

```python
from nexusrag_sdk.models.audit_event_response import AuditEventResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AuditEventResponse from a JSON string
audit_event_response_instance = AuditEventResponse.from_json(json)
# print the JSON string representation of the object
print(AuditEventResponse.to_json())

# convert the object into a dict
audit_event_response_dict = audit_event_response_instance.to_dict()
# create an instance of AuditEventResponse from a dict
audit_event_response_from_dict = AuditEventResponse.from_dict(audit_event_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


