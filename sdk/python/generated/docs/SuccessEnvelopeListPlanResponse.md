# SuccessEnvelopeListPlanResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**List[NexusragAppsApiRoutesAdminPlanResponse]**](NexusragAppsApiRoutesAdminPlanResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_list_plan_response import SuccessEnvelopeListPlanResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeListPlanResponse from a JSON string
success_envelope_list_plan_response_instance = SuccessEnvelopeListPlanResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeListPlanResponse.to_json())

# convert the object into a dict
success_envelope_list_plan_response_dict = success_envelope_list_plan_response_instance.to_dict()
# create an instance of SuccessEnvelopeListPlanResponse from a dict
success_envelope_list_plan_response_from_dict = SuccessEnvelopeListPlanResponse.from_dict(success_envelope_list_plan_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


