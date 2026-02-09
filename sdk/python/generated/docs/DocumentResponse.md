# DocumentResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**tenant_id** | **str** |  | 
**corpus_id** | **str** |  | 
**filename** | **str** |  | 
**content_type** | **str** |  | 
**source** | **str** |  | 
**ingest_source** | **str** |  | 
**status** | **str** |  | 
**failure_reason** | **str** |  | 
**created_at** | **str** |  | 
**updated_at** | **str** |  | 
**queued_at** | **str** |  | 
**processing_started_at** | **str** |  | 
**completed_at** | **str** |  | 
**last_reindexed_at** | **str** |  | 
**last_job_id** | **str** |  | 
**num_chunks** | **int** |  | [optional] 

## Example

```python
from nexusrag_sdk.models.document_response import DocumentResponse

# TODO update the JSON string below
json = "{}"
# create an instance of DocumentResponse from a JSON string
document_response_instance = DocumentResponse.from_json(json)
# print the JSON string representation of the object
print(DocumentResponse.to_json())

# convert the object into a dict
document_response_dict = document_response_instance.to_dict()
# create an instance of DocumentResponse from a dict
document_response_from_dict = DocumentResponse.from_dict(document_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


