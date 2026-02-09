# UsageTimeseriesResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**metric** | **str** |  | 
**granularity** | **str** |  | 
**points** | **List[Dict[str, object]]** |  | 

## Example

```python
from nexusrag_sdk.models.usage_timeseries_response import UsageTimeseriesResponse

# TODO update the JSON string below
json = "{}"
# create an instance of UsageTimeseriesResponse from a JSON string
usage_timeseries_response_instance = UsageTimeseriesResponse.from_json(json)
# print the JSON string representation of the object
print(UsageTimeseriesResponse.to_json())

# convert the object into a dict
usage_timeseries_response_dict = usage_timeseries_response_instance.to_dict()
# create an instance of UsageTimeseriesResponse from a dict
usage_timeseries_response_from_dict = UsageTimeseriesResponse.from_dict(usage_timeseries_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


