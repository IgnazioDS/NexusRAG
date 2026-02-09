# RunRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**session_id** | **str** |  | 
**corpus_id** | **str** |  | 
**message** | **str** |  | 
**top_k** | **int** |  | [optional] [default to 5]
**audio** | **bool** |  | [optional] [default to False]

## Example

```python
from nexusrag_sdk.models.run_request import RunRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RunRequest from a JSON string
run_request_instance = RunRequest.from_json(json)
# print the JSON string representation of the object
print(RunRequest.to_json())

# convert the object into a dict
run_request_dict = run_request_instance.to_dict()
# create an instance of RunRequest from a dict
run_request_from_dict = RunRequest.from_dict(run_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


