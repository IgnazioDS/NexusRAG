# ResponseMeta


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**request_id** | **str** |  | 
**api_version** | **str** |  | [optional] [default to 'v1']

## Example

```python
from nexusrag_sdk.models.response_meta import ResponseMeta

# TODO update the JSON string below
json = "{}"
# create an instance of ResponseMeta from a JSON string
response_meta_instance = ResponseMeta.from_json(json)
# print the JSON string representation of the object
print(ResponseMeta.to_json())

# convert the object into a dict
response_meta_dict = response_meta_instance.to_dict()
# create an instance of ResponseMeta from a dict
response_meta_from_dict = ResponseMeta.from_dict(response_meta_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


