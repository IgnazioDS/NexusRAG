# ReindexRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**chunk_size_chars** | **int** |  | [optional] 
**chunk_overlap_chars** | **int** |  | [optional] 

## Example

```python
from nexusrag_sdk.models.reindex_request import ReindexRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ReindexRequest from a JSON string
reindex_request_instance = ReindexRequest.from_json(json)
# print the JSON string representation of the object
print(ReindexRequest.to_json())

# convert the object into a dict
reindex_request_dict = reindex_request_instance.to_dict()
# create an instance of ReindexRequest from a dict
reindex_request_from_dict = ReindexRequest.from_dict(reindex_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


