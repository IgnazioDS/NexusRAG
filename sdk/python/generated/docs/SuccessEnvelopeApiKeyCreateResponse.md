# SuccessEnvelopeApiKeyCreateResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**ApiKeyCreateResponse**](ApiKeyCreateResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_api_key_create_response import SuccessEnvelopeApiKeyCreateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeApiKeyCreateResponse from a JSON string
success_envelope_api_key_create_response_instance = SuccessEnvelopeApiKeyCreateResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeApiKeyCreateResponse.to_json())

# convert the object into a dict
success_envelope_api_key_create_response_dict = success_envelope_api_key_create_response_instance.to_dict()
# create an instance of SuccessEnvelopeApiKeyCreateResponse from a dict
success_envelope_api_key_create_response_from_dict = SuccessEnvelopeApiKeyCreateResponse.from_dict(success_envelope_api_key_create_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


