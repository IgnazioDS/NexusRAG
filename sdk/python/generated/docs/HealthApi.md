# nexusrag_sdk.HealthApi

All URIs are relative to *http://localhost:8000*

Method | HTTP request | Description
------------- | ------------- | -------------
[**health_v1_health_get**](HealthApi.md#health_v1_health_get) | **GET** /v1/health | Health


# **health_v1_health_get**
> SuccessEnvelopeHealthResponse health_v1_health_get()

Health

### Example


```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_health_response import SuccessEnvelopeHealthResponse
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
    api_instance = nexusrag_sdk.HealthApi(api_client)

    try:
        # Health
        api_response = api_instance.health_v1_health_get()
        print("The response of HealthApi->health_v1_health_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling HealthApi->health_v1_health_get: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SuccessEnvelopeHealthResponse**](SuccessEnvelopeHealthResponse.md)

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

