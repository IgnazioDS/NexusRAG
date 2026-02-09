# NexusragAppsApiRoutesAdminPlanResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**name** | **str** |  | 
**is_active** | **bool** |  | 
**features** | [**List[PlanFeatureResponse]**](PlanFeatureResponse.md) |  | 

## Example

```python
from nexusrag_sdk.models.nexusrag_apps_api_routes_admin_plan_response import NexusragAppsApiRoutesAdminPlanResponse

# TODO update the JSON string below
json = "{}"
# create an instance of NexusragAppsApiRoutesAdminPlanResponse from a JSON string
nexusrag_apps_api_routes_admin_plan_response_instance = NexusragAppsApiRoutesAdminPlanResponse.from_json(json)
# print the JSON string representation of the object
print(NexusragAppsApiRoutesAdminPlanResponse.to_json())

# convert the object into a dict
nexusrag_apps_api_routes_admin_plan_response_dict = nexusrag_apps_api_routes_admin_plan_response_instance.to_dict()
# create an instance of NexusragAppsApiRoutesAdminPlanResponse from a dict
nexusrag_apps_api_routes_admin_plan_response_from_dict = NexusragAppsApiRoutesAdminPlanResponse.from_dict(nexusrag_apps_api_routes_admin_plan_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


