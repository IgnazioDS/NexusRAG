# ErrorEnvelope


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**error** | [**ErrorDetail**](ErrorDetail.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.error_envelope import ErrorEnvelope

# TODO update the JSON string below
json = "{}"
# create an instance of ErrorEnvelope from a JSON string
error_envelope_instance = ErrorEnvelope.from_json(json)
# print the JSON string representation of the object
print(ErrorEnvelope.to_json())

# convert the object into a dict
error_envelope_dict = error_envelope_instance.to_dict()
# create an instance of ErrorEnvelope from a dict
error_envelope_from_dict = ErrorEnvelope.from_dict(error_envelope_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


