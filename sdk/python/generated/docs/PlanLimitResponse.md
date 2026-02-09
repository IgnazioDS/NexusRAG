# PlanLimitResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**tenant_id** | **str** |  | 
**daily_requests_limit** | **int** |  | 
**monthly_requests_limit** | **int** |  | 
**daily_tokens_limit** | **int** |  | 
**monthly_tokens_limit** | **int** |  | 
**soft_cap_ratio** | **float** |  | 
**hard_cap_enabled** | **bool** |  | 

## Example

```python
from nexusrag_sdk.models.plan_limit_response import PlanLimitResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PlanLimitResponse from a JSON string
plan_limit_response_instance = PlanLimitResponse.from_json(json)
# print the JSON string representation of the object
print(PlanLimitResponse.to_json())

# convert the object into a dict
plan_limit_response_dict = plan_limit_response_instance.to_dict()
# create an instance of PlanLimitResponse from a dict
plan_limit_response_from_dict = PlanLimitResponse.from_dict(plan_limit_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


