# SuccessEnvelopeCorpusResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**CorpusResponse**](CorpusResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_corpus_response import SuccessEnvelopeCorpusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeCorpusResponse from a JSON string
success_envelope_corpus_response_instance = SuccessEnvelopeCorpusResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeCorpusResponse.to_json())

# convert the object into a dict
success_envelope_corpus_response_dict = success_envelope_corpus_response_instance.to_dict()
# create an instance of SuccessEnvelopeCorpusResponse from a dict
success_envelope_corpus_response_from_dict = SuccessEnvelopeCorpusResponse.from_dict(success_envelope_corpus_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


