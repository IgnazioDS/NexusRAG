# SuccessEnvelopeApiKeyResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**ApiKeyResponse**](ApiKeyResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_api_key_response import SuccessEnvelopeApiKeyResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeApiKeyResponse from a JSON string
success_envelope_api_key_response_instance = SuccessEnvelopeApiKeyResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeApiKeyResponse.to_json())

# convert the object into a dict
success_envelope_api_key_response_dict = success_envelope_api_key_response_instance.to_dict()
# create an instance of SuccessEnvelopeApiKeyResponse from a dict
success_envelope_api_key_response_from_dict = SuccessEnvelopeApiKeyResponse.from_dict(success_envelope_api_key_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


