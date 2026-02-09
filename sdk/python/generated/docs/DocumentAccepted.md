# DocumentAccepted


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**document_id** | **str** |  | 
**status** | **str** |  | 
**job_id** | **str** |  | 
**status_url** | **str** |  | 

## Example

```python
from nexusrag_sdk.models.document_accepted import DocumentAccepted

# TODO update the JSON string below
json = "{}"
# create an instance of DocumentAccepted from a JSON string
document_accepted_instance = DocumentAccepted.from_json(json)
# print the JSON string representation of the object
print(DocumentAccepted.to_json())

# convert the object into a dict
document_accepted_dict = document_accepted_instance.to_dict()
# create an instance of DocumentAccepted from a dict
document_accepted_from_dict = DocumentAccepted.from_dict(document_accepted_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


