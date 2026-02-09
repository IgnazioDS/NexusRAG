# TextIngestRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**corpus_id** | **str** |  | 
**text** | **str** |  | 
**document_id** | **str** |  | [optional] 
**filename** | **str** |  | [optional] 
**metadata_json** | **Dict[str, object]** |  | [optional] 
**chunk_size_chars** | **int** |  | [optional] 
**chunk_overlap_chars** | **int** |  | [optional] 
**overwrite** | **bool** |  | [optional] [default to False]

## Example

```python
from nexusrag_sdk.models.text_ingest_request import TextIngestRequest

# TODO update the JSON string below
json = "{}"
# create an instance of TextIngestRequest from a JSON string
text_ingest_request_instance = TextIngestRequest.from_json(json)
# print the JSON string representation of the object
print(TextIngestRequest.to_json())

# convert the object into a dict
text_ingest_request_dict = text_ingest_request_instance.to_dict()
# create an instance of TextIngestRequest from a dict
text_ingest_request_from_dict = TextIngestRequest.from_dict(text_ingest_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


