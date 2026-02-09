# SuccessEnvelopeListDocumentResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**List[DocumentResponse]**](DocumentResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_list_document_response import SuccessEnvelopeListDocumentResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeListDocumentResponse from a JSON string
success_envelope_list_document_response_instance = SuccessEnvelopeListDocumentResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeListDocumentResponse.to_json())

# convert the object into a dict
success_envelope_list_document_response_dict = success_envelope_list_document_response_instance.to_dict()
# create an instance of SuccessEnvelopeListDocumentResponse from a dict
success_envelope_list_document_response_from_dict = SuccessEnvelopeListDocumentResponse.from_dict(success_envelope_list_document_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


