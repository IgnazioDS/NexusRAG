# SuccessEnvelopePlanLimitResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**PlanLimitResponse**](PlanLimitResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_plan_limit_response import SuccessEnvelopePlanLimitResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopePlanLimitResponse from a JSON string
success_envelope_plan_limit_response_instance = SuccessEnvelopePlanLimitResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopePlanLimitResponse.to_json())

# convert the object into a dict
success_envelope_plan_limit_response_dict = success_envelope_plan_limit_response_instance.to_dict()
# create an instance of SuccessEnvelopePlanLimitResponse from a dict
success_envelope_plan_limit_response_from_dict = SuccessEnvelopePlanLimitResponse.from_dict(success_envelope_plan_limit_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


