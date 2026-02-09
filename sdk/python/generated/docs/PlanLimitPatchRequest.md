# PlanLimitPatchRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**daily_requests_limit** | **int** |  | [optional] 
**monthly_requests_limit** | **int** |  | [optional] 
**daily_tokens_limit** | **int** |  | [optional] 
**monthly_tokens_limit** | **int** |  | [optional] 
**soft_cap_ratio** | **float** |  | [optional] 
**hard_cap_enabled** | **bool** |  | [optional] 

## Example

```python
from nexusrag_sdk.models.plan_limit_patch_request import PlanLimitPatchRequest

# TODO update the JSON string below
json = "{}"
# create an instance of PlanLimitPatchRequest from a JSON string
plan_limit_patch_request_instance = PlanLimitPatchRequest.from_json(json)
# print the JSON string representation of the object
print(PlanLimitPatchRequest.to_json())

# convert the object into a dict
plan_limit_patch_request_dict = plan_limit_patch_request_instance.to_dict()
# create an instance of PlanLimitPatchRequest from a dict
plan_limit_patch_request_from_dict = PlanLimitPatchRequest.from_dict(plan_limit_patch_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


