# SuccessEnvelopePlanUpgradeResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**PlanUpgradeResponse**](PlanUpgradeResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_plan_upgrade_response import SuccessEnvelopePlanUpgradeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopePlanUpgradeResponse from a JSON string
success_envelope_plan_upgrade_response_instance = SuccessEnvelopePlanUpgradeResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopePlanUpgradeResponse.to_json())

# convert the object into a dict
success_envelope_plan_upgrade_response_dict = success_envelope_plan_upgrade_response_instance.to_dict()
# create an instance of SuccessEnvelopePlanUpgradeResponse from a dict
success_envelope_plan_upgrade_response_from_dict = SuccessEnvelopePlanUpgradeResponse.from_dict(success_envelope_plan_upgrade_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


