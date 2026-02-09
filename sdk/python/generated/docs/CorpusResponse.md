# CorpusResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**tenant_id** | **str** |  | 
**name** | **str** |  | 
**provider_config_json** | **Dict[str, object]** |  | 
**created_at** | **str** |  | 

## Example

```python
from nexusrag_sdk.models.corpus_response import CorpusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of CorpusResponse from a JSON string
corpus_response_instance = CorpusResponse.from_json(json)
# print the JSON string representation of the object
print(CorpusResponse.to_json())

# convert the object into a dict
corpus_response_dict = corpus_response_instance.to_dict()
# create an instance of CorpusResponse from a dict
corpus_response_from_dict = CorpusResponse.from_dict(corpus_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


