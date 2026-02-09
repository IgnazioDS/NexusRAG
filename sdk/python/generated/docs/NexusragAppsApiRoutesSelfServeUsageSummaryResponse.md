# NexusragAppsApiRoutesSelfServeUsageSummaryResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**window_days** | **int** |  | 
**requests** | **Dict[str, object]** |  | 
**quota** | **Dict[str, object]** |  | 
**rate_limit_hits** | **Dict[str, object]** |  | 
**ingestion** | **Dict[str, object]** |  | 

## Example

```python
from nexusrag_sdk.models.nexusrag_apps_api_routes_self_serve_usage_summary_response import NexusragAppsApiRoutesSelfServeUsageSummaryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of NexusragAppsApiRoutesSelfServeUsageSummaryResponse from a JSON string
nexusrag_apps_api_routes_self_serve_usage_summary_response_instance = NexusragAppsApiRoutesSelfServeUsageSummaryResponse.from_json(json)
# print the JSON string representation of the object
print(NexusragAppsApiRoutesSelfServeUsageSummaryResponse.to_json())

# convert the object into a dict
nexusrag_apps_api_routes_self_serve_usage_summary_response_dict = nexusrag_apps_api_routes_self_serve_usage_summary_response_instance.to_dict()
# create an instance of NexusragAppsApiRoutesSelfServeUsageSummaryResponse from a dict
nexusrag_apps_api_routes_self_serve_usage_summary_response_from_dict = NexusragAppsApiRoutesSelfServeUsageSummaryResponse.from_dict(nexusrag_apps_api_routes_self_serve_usage_summary_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


