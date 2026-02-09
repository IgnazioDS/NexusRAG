# SuccessEnvelopeApiKeyListResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**ApiKeyListResponse**](ApiKeyListResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_api_key_list_response import SuccessEnvelopeApiKeyListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeApiKeyListResponse from a JSON string
success_envelope_api_key_list_response_instance = SuccessEnvelopeApiKeyListResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeApiKeyListResponse.to_json())

# convert the object into a dict
success_envelope_api_key_list_response_dict = success_envelope_api_key_list_response_instance.to_dict()
# create an instance of SuccessEnvelopeApiKeyListResponse from a dict
success_envelope_api_key_list_response_from_dict = SuccessEnvelopeApiKeyListResponse.from_dict(success_envelope_api_key_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


