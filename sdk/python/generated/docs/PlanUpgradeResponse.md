# PlanUpgradeResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**request_id** | **int** |  | 
**status** | **str** |  | 

## Example

```python
from nexusrag_sdk.models.plan_upgrade_response import PlanUpgradeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PlanUpgradeResponse from a JSON string
plan_upgrade_response_instance = PlanUpgradeResponse.from_json(json)
# print the JSON string representation of the object
print(PlanUpgradeResponse.to_json())

# convert the object into a dict
plan_upgrade_response_dict = plan_upgrade_response_instance.to_dict()
# create an instance of PlanUpgradeResponse from a dict
plan_upgrade_response_from_dict = PlanUpgradeResponse.from_dict(plan_upgrade_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


