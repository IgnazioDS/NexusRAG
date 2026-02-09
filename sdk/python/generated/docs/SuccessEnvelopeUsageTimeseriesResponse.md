# SuccessEnvelopeUsageTimeseriesResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**UsageTimeseriesResponse**](UsageTimeseriesResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_usage_timeseries_response import SuccessEnvelopeUsageTimeseriesResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeUsageTimeseriesResponse from a JSON string
success_envelope_usage_timeseries_response_instance = SuccessEnvelopeUsageTimeseriesResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeUsageTimeseriesResponse.to_json())

# convert the object into a dict
success_envelope_usage_timeseries_response_dict = success_envelope_usage_timeseries_response_instance.to_dict()
# create an instance of SuccessEnvelopeUsageTimeseriesResponse from a dict
success_envelope_usage_timeseries_response_from_dict = SuccessEnvelopeUsageTimeseriesResponse.from_dict(success_envelope_usage_timeseries_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


