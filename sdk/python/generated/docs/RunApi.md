# nexusrag_sdk.RunApi

All URIs are relative to *http://localhost:8000*

Method | HTTP request | Description
------------- | ------------- | -------------
[**run_v1_run_post**](RunApi.md#run_v1_run_post) | **POST** /v1/run | Run


# **run_v1_run_post**
> object run_v1_run_post(run_request)

Run

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.run_request import RunRequest
from nexusrag_sdk.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost:8000
# See configuration.py for a list of all supported configuration parameters.
configuration = nexusrag_sdk.Configuration(
    host = "http://localhost:8000"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: BearerAuth
configuration = nexusrag_sdk.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with nexusrag_sdk.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = nexusrag_sdk.RunApi(api_client)
    run_request = nexusrag_sdk.RunRequest() # RunRequest | 

    try:
        # Run
        api_response = api_instance.run_v1_run_post(run_request)
        print("The response of RunApi->run_v1_run_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RunApi->run_v1_run_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **run_request** | [**RunRequest**](RunRequest.md)|  | 

### Return type

**object**

### Authorization

[BearerAuth](../README.md#BearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
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

