# SuccessEnvelopeDictStrAny


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | **Dict[str, object]** |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_dict_str_any import SuccessEnvelopeDictStrAny

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeDictStrAny from a JSON string
success_envelope_dict_str_any_instance = SuccessEnvelopeDictStrAny.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeDictStrAny.to_json())

# convert the object into a dict
success_envelope_dict_str_any_dict = success_envelope_dict_str_any_instance.to_dict()
# create an instance of SuccessEnvelopeDictStrAny from a dict
success_envelope_dict_str_any_from_dict = SuccessEnvelopeDictStrAny.from_dict(success_envelope_dict_str_any_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


