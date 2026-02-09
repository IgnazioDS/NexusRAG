# nexusrag_sdk.OpsApi

All URIs are relative to *http://localhost:8000*

Method | HTTP request | Description
------------- | ------------- | -------------
[**ops_health_v1_ops_health_get**](OpsApi.md#ops_health_v1_ops_health_get) | **GET** /v1/ops/health | Ops Health
[**ops_ingestion_v1_ops_ingestion_get**](OpsApi.md#ops_ingestion_v1_ops_ingestion_get) | **GET** /v1/ops/ingestion | Ops Ingestion
[**ops_metrics_v1_ops_metrics_get**](OpsApi.md#ops_metrics_v1_ops_metrics_get) | **GET** /v1/ops/metrics | Ops Metrics


# **ops_health_v1_ops_health_get**
> SuccessEnvelopeDictStrAny ops_health_v1_ops_health_get()

Ops Health

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_dict_str_any import SuccessEnvelopeDictStrAny
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
    api_instance = nexusrag_sdk.OpsApi(api_client)

    try:
        # Ops Health
        api_response = api_instance.ops_health_v1_ops_health_get()
        print("The response of OpsApi->ops_health_v1_ops_health_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling OpsApi->ops_health_v1_ops_health_get: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SuccessEnvelopeDictStrAny**](SuccessEnvelopeDictStrAny.md)

### Authorization

[BearerAuth](../README.md#BearerAuth)

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

# **ops_ingestion_v1_ops_ingestion_get**
> SuccessEnvelopeDictStrAny ops_ingestion_v1_ops_ingestion_get(hours=hours)

Ops Ingestion

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_dict_str_any import SuccessEnvelopeDictStrAny
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
    api_instance = nexusrag_sdk.OpsApi(api_client)
    hours = 24 # int |  (optional) (default to 24)

    try:
        # Ops Ingestion
        api_response = api_instance.ops_ingestion_v1_ops_ingestion_get(hours=hours)
        print("The response of OpsApi->ops_ingestion_v1_ops_ingestion_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling OpsApi->ops_ingestion_v1_ops_ingestion_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **hours** | **int**|  | [optional] [default to 24]

### Return type

[**SuccessEnvelopeDictStrAny**](SuccessEnvelopeDictStrAny.md)

### Authorization

[BearerAuth](../README.md#BearerAuth)

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

# **ops_metrics_v1_ops_metrics_get**
> SuccessEnvelopeDictStrAny ops_metrics_v1_ops_metrics_get()

Ops Metrics

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_dict_str_any import SuccessEnvelopeDictStrAny
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
    api_instance = nexusrag_sdk.OpsApi(api_client)

    try:
        # Ops Metrics
        api_response = api_instance.ops_metrics_v1_ops_metrics_get()
        print("The response of OpsApi->ops_metrics_v1_ops_metrics_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling OpsApi->ops_metrics_v1_ops_metrics_get: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SuccessEnvelopeDictStrAny**](SuccessEnvelopeDictStrAny.md)

### Authorization

[BearerAuth](../README.md#BearerAuth)

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

