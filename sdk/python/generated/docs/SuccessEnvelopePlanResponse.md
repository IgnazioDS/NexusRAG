# SuccessEnvelopePlanResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**NexusragAppsApiRoutesSelfServePlanResponse**](NexusragAppsApiRoutesSelfServePlanResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_plan_response import SuccessEnvelopePlanResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopePlanResponse from a JSON string
success_envelope_plan_response_instance = SuccessEnvelopePlanResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopePlanResponse.to_json())

# convert the object into a dict
success_envelope_plan_response_dict = success_envelope_plan_response_instance.to_dict()
# create an instance of SuccessEnvelopePlanResponse from a dict
success_envelope_plan_response_from_dict = SuccessEnvelopePlanResponse.from_dict(success_envelope_plan_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


