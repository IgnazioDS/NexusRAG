# NexusragAppsApiRoutesAdminUsageSummaryResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**tenant_id** | **str** |  | 
**period_type** | **str** |  | 
**period_start** | **str** |  | 
**requests_count** | **int** |  | 
**estimated_tokens_count** | **int** |  | 

## Example

```python
from nexusrag_sdk.models.nexusrag_apps_api_routes_admin_usage_summary_response import NexusragAppsApiRoutesAdminUsageSummaryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of NexusragAppsApiRoutesAdminUsageSummaryResponse from a JSON string
nexusrag_apps_api_routes_admin_usage_summary_response_instance = NexusragAppsApiRoutesAdminUsageSummaryResponse.from_json(json)
# print the JSON string representation of the object
print(NexusragAppsApiRoutesAdminUsageSummaryResponse.to_json())

# convert the object into a dict
nexusrag_apps_api_routes_admin_usage_summary_response_dict = nexusrag_apps_api_routes_admin_usage_summary_response_instance.to_dict()
# create an instance of NexusragAppsApiRoutesAdminUsageSummaryResponse from a dict
nexusrag_apps_api_routes_admin_usage_summary_response_from_dict = NexusragAppsApiRoutesAdminUsageSummaryResponse.from_dict(nexusrag_apps_api_routes_admin_usage_summary_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


