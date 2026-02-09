# SuccessEnvelopeDocumentAccepted


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**DocumentAccepted**](DocumentAccepted.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_document_accepted import SuccessEnvelopeDocumentAccepted

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeDocumentAccepted from a JSON string
success_envelope_document_accepted_instance = SuccessEnvelopeDocumentAccepted.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeDocumentAccepted.to_json())

# convert the object into a dict
success_envelope_document_accepted_dict = success_envelope_document_accepted_instance.to_dict()
# create an instance of SuccessEnvelopeDocumentAccepted from a dict
success_envelope_document_accepted_from_dict = SuccessEnvelopeDocumentAccepted.from_dict(success_envelope_document_accepted_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


