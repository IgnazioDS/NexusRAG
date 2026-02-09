# NexusragAppsApiRoutesSelfServePlanResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**tenant_id** | **str** |  | 
**plan_id** | **str** |  | 
**plan_name** | **str** |  | 
**entitlements** | **List[Dict[str, object]]** |  | 
**quota** | **Dict[str, object]** |  | 

## Example

```python
from nexusrag_sdk.models.nexusrag_apps_api_routes_self_serve_plan_response import NexusragAppsApiRoutesSelfServePlanResponse

# TODO update the JSON string below
json = "{}"
# create an instance of NexusragAppsApiRoutesSelfServePlanResponse from a JSON string
nexusrag_apps_api_routes_self_serve_plan_response_instance = NexusragAppsApiRoutesSelfServePlanResponse.from_json(json)
# print the JSON string representation of the object
print(NexusragAppsApiRoutesSelfServePlanResponse.to_json())

# convert the object into a dict
nexusrag_apps_api_routes_self_serve_plan_response_dict = nexusrag_apps_api_routes_self_serve_plan_response_instance.to_dict()
# create an instance of NexusragAppsApiRoutesSelfServePlanResponse from a dict
nexusrag_apps_api_routes_self_serve_plan_response_from_dict = NexusragAppsApiRoutesSelfServePlanResponse.from_dict(nexusrag_apps_api_routes_self_serve_plan_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


