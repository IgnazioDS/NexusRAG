# AuditEventsPage


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[AuditEventResponse]**](AuditEventResponse.md) |  | 
**next_offset** | **int** |  | 

## Example

```python
from nexusrag_sdk.models.audit_events_page import AuditEventsPage

# TODO update the JSON string below
json = "{}"
# create an instance of AuditEventsPage from a JSON string
audit_events_page_instance = AuditEventsPage.from_json(json)
# print the JSON string representation of the object
print(AuditEventsPage.to_json())

# convert the object into a dict
audit_events_page_dict = audit_events_page_instance.to_dict()
# create an instance of AuditEventsPage from a dict
audit_events_page_from_dict = AuditEventsPage.from_dict(audit_events_page_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


