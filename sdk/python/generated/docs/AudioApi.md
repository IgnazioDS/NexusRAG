# nexusrag_sdk.AudioApi

All URIs are relative to *http://localhost:8000*

Method | HTTP request | Description
------------- | ------------- | -------------
[**get_audio_v1_audio_audio_id_mp3_get**](AudioApi.md#get_audio_v1_audio_audio_id_mp3_get) | **GET** /v1/audio/{audio_id}.mp3 | Get Audio


# **get_audio_v1_audio_audio_id_mp3_get**
> object get_audio_v1_audio_audio_id_mp3_get(audio_id)

Get Audio

### Example


```python
import nexusrag_sdk
from nexusrag_sdk.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost:8000
# See configuration.py for a list of all supported configuration parameters.
configuration = nexusrag_sdk.Configuration(
    host = "http://localhost:8000"
)


# Enter a context with an instance of the API client
with nexusrag_sdk.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = nexusrag_sdk.AudioApi(api_client)
    audio_id = 'audio_id_example' # str | 

    try:
        # Get Audio
        api_response = api_instance.get_audio_v1_audio_audio_id_mp3_get(audio_id)
        print("The response of AudioApi->get_audio_v1_audio_audio_id_mp3_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AudioApi->get_audio_v1_audio_audio_id_mp3_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **audio_id** | **str**|  | 

### Return type

**object**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**400** | Bad request |  -  |
**401** | Unauthorized |  -  |
**402** | Quota exceeded |  -  |
**403** | Forbidden |  -  |
**404** | Not found |  -  |
**409** | Conflict |  -  |
**422** | Validation error |  -  |
**429** | Rate limited |  -  |
**500** | Internal server error |  -  |
**503** | Service unavailable |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

