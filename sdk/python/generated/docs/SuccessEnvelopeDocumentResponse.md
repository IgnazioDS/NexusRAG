# SuccessEnvelopeDocumentResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**DocumentResponse**](DocumentResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_document_response import SuccessEnvelopeDocumentResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeDocumentResponse from a JSON string
success_envelope_document_response_instance = SuccessEnvelopeDocumentResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeDocumentResponse.to_json())

# convert the object into a dict
success_envelope_document_response_dict = success_envelope_document_response_instance.to_dict()
# create an instance of SuccessEnvelopeDocumentResponse from a dict
success_envelope_document_response_from_dict = SuccessEnvelopeDocumentResponse.from_dict(success_envelope_document_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


