# SuccessEnvelopeListCorpusResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**List[CorpusResponse]**](CorpusResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_list_corpus_response import SuccessEnvelopeListCorpusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeListCorpusResponse from a JSON string
success_envelope_list_corpus_response_instance = SuccessEnvelopeListCorpusResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeListCorpusResponse.to_json())

# convert the object into a dict
success_envelope_list_corpus_response_dict = success_envelope_list_corpus_response_instance.to_dict()
# create an instance of SuccessEnvelopeListCorpusResponse from a dict
success_envelope_list_corpus_response_from_dict = SuccessEnvelopeListCorpusResponse.from_dict(success_envelope_list_corpus_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


