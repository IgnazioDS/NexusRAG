# FeatureOverrideRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**feature_key** | **str** |  | 
**enabled** | **bool** |  | [optional] 
**config_json** | **Dict[str, object]** |  | [optional] 

## Example

```python
from nexusrag_sdk.models.feature_override_request import FeatureOverrideRequest

# TODO update the JSON string below
json = "{}"
# create an instance of FeatureOverrideRequest from a JSON string
feature_override_request_instance = FeatureOverrideRequest.from_json(json)
# print the JSON string representation of the object
print(FeatureOverrideRequest.to_json())

# convert the object into a dict
feature_override_request_dict = feature_override_request_instance.to_dict()
# create an instance of FeatureOverrideRequest from a dict
feature_override_request_from_dict = FeatureOverrideRequest.from_dict(feature_override_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


