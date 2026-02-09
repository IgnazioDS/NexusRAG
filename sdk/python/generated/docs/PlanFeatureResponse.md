# PlanFeatureResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**feature_key** | **str** |  | 
**enabled** | **bool** |  | 
**config_json** | **Dict[str, object]** |  | 

## Example

```python
from nexusrag_sdk.models.plan_feature_response import PlanFeatureResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PlanFeatureResponse from a JSON string
plan_feature_response_instance = PlanFeatureResponse.from_json(json)
# print the JSON string representation of the object
print(PlanFeatureResponse.to_json())

# convert the object into a dict
plan_feature_response_dict = plan_feature_response_instance.to_dict()
# create an instance of PlanFeatureResponse from a dict
plan_feature_response_from_dict = PlanFeatureResponse.from_dict(plan_feature_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


