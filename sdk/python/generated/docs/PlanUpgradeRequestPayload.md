# PlanUpgradeRequestPayload


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**target_plan** | **str** |  | 
**reason** | **str** |  | [optional] 

## Example

```python
from nexusrag_sdk.models.plan_upgrade_request_payload import PlanUpgradeRequestPayload

# TODO update the JSON string below
json = "{}"
# create an instance of PlanUpgradeRequestPayload from a JSON string
plan_upgrade_request_payload_instance = PlanUpgradeRequestPayload.from_json(json)
# print the JSON string representation of the object
print(PlanUpgradeRequestPayload.to_json())

# convert the object into a dict
plan_upgrade_request_payload_dict = plan_upgrade_request_payload_instance.to_dict()
# create an instance of PlanUpgradeRequestPayload from a dict
plan_upgrade_request_payload_from_dict = PlanUpgradeRequestPayload.from_dict(plan_upgrade_request_payload_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


