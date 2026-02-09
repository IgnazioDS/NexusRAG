# CorpusPatchRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** |  | [optional] 
**provider_config_json** | **Dict[str, object]** |  | [optional] 

## Example

```python
from nexusrag_sdk.models.corpus_patch_request import CorpusPatchRequest

# TODO update the JSON string below
json = "{}"
# create an instance of CorpusPatchRequest from a JSON string
corpus_patch_request_instance = CorpusPatchRequest.from_json(json)
# print the JSON string representation of the object
print(CorpusPatchRequest.to_json())

# convert the object into a dict
corpus_patch_request_dict = corpus_patch_request_instance.to_dict()
# create an instance of CorpusPatchRequest from a dict
corpus_patch_request_from_dict = CorpusPatchRequest.from_dict(corpus_patch_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


