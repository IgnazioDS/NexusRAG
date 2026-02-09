# TenantPlanResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**tenant_id** | **str** |  | 
**plan_id** | **str** |  | 
**plan_name** | **str** |  | 
**effective_from** | **str** |  | 
**effective_to** | **str** |  | 
**is_active** | **bool** |  | 
**entitlements** | [**List[PlanFeatureResponse]**](PlanFeatureResponse.md) |  | 

## Example

```python
from nexusrag_sdk.models.tenant_plan_response import TenantPlanResponse

# TODO update the JSON string below
json = "{}"
# create an instance of TenantPlanResponse from a JSON string
tenant_plan_response_instance = TenantPlanResponse.from_json(json)
# print the JSON string representation of the object
print(TenantPlanResponse.to_json())

# convert the object into a dict
tenant_plan_response_dict = tenant_plan_response_instance.to_dict()
# create an instance of TenantPlanResponse from a dict
tenant_plan_response_from_dict = TenantPlanResponse.from_dict(tenant_plan_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


