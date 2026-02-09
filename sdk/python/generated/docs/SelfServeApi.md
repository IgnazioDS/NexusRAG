# nexusrag_sdk.SelfServeApi

All URIs are relative to *http://localhost:8000*

Method | HTTP request | Description
------------- | ------------- | -------------
[**billing_webhook_test_v1_self_serve_billing_webhook_test_post**](SelfServeApi.md#billing_webhook_test_v1_self_serve_billing_webhook_test_post) | **POST** /v1/self-serve/billing/webhook-test | Billing Webhook Test
[**create_api_key_v1_self_serve_api_keys_post**](SelfServeApi.md#create_api_key_v1_self_serve_api_keys_post) | **POST** /v1/self-serve/api-keys | Create Api Key
[**get_self_serve_plan_v1_self_serve_plan_get**](SelfServeApi.md#get_self_serve_plan_v1_self_serve_plan_get) | **GET** /v1/self-serve/plan | Get Self Serve Plan
[**list_api_keys_v1_self_serve_api_keys_get**](SelfServeApi.md#list_api_keys_v1_self_serve_api_keys_get) | **GET** /v1/self-serve/api-keys | List Api Keys
[**revoke_api_key_v1_self_serve_api_keys_key_id_revoke_post**](SelfServeApi.md#revoke_api_key_v1_self_serve_api_keys_key_id_revoke_post) | **POST** /v1/self-serve/api-keys/{key_id}/revoke | Revoke Api Key
[**upgrade_plan_request_v1_self_serve_plan_upgrade_request_post**](SelfServeApi.md#upgrade_plan_request_v1_self_serve_plan_upgrade_request_post) | **POST** /v1/self-serve/plan/upgrade-request | Upgrade Plan Request
[**usage_summary_v1_self_serve_usage_summary_get**](SelfServeApi.md#usage_summary_v1_self_serve_usage_summary_get) | **GET** /v1/self-serve/usage/summary | Usage Summary
[**usage_timeseries_v1_self_serve_usage_timeseries_get**](SelfServeApi.md#usage_timeseries_v1_self_serve_usage_timeseries_get) | **GET** /v1/self-serve/usage/timeseries | Usage Timeseries


# **billing_webhook_test_v1_self_serve_billing_webhook_test_post**
> SuccessEnvelopeBillingWebhookTestResponse billing_webhook_test_v1_self_serve_billing_webhook_test_post()

Billing Webhook Test

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_billing_webhook_test_response import SuccessEnvelopeBillingWebhookTestResponse
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
    api_instance = nexusrag_sdk.SelfServeApi(api_client)

    try:
        # Billing Webhook Test
        api_response = api_instance.billing_webhook_test_v1_self_serve_billing_webhook_test_post()
        print("The response of SelfServeApi->billing_webhook_test_v1_self_serve_billing_webhook_test_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SelfServeApi->billing_webhook_test_v1_self_serve_billing_webhook_test_post: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SuccessEnvelopeBillingWebhookTestResponse**](SuccessEnvelopeBillingWebhookTestResponse.md)

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

# **create_api_key_v1_self_serve_api_keys_post**
> SuccessEnvelopeApiKeyCreateResponse create_api_key_v1_self_serve_api_keys_post(api_key_create_request, idempotency_key=idempotency_key)

Create Api Key

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.api_key_create_request import ApiKeyCreateRequest
from nexusrag_sdk.models.success_envelope_api_key_create_response import SuccessEnvelopeApiKeyCreateResponse
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
    api_instance = nexusrag_sdk.SelfServeApi(api_client)
    api_key_create_request = nexusrag_sdk.ApiKeyCreateRequest() # ApiKeyCreateRequest | 
    idempotency_key = 'idempotency_key_example' # str |  (optional)

    try:
        # Create Api Key
        api_response = api_instance.create_api_key_v1_self_serve_api_keys_post(api_key_create_request, idempotency_key=idempotency_key)
        print("The response of SelfServeApi->create_api_key_v1_self_serve_api_keys_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SelfServeApi->create_api_key_v1_self_serve_api_keys_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **api_key_create_request** | [**ApiKeyCreateRequest**](ApiKeyCreateRequest.md)|  | 
 **idempotency_key** | **str**|  | [optional] 

### Return type

[**SuccessEnvelopeApiKeyCreateResponse**](SuccessEnvelopeApiKeyCreateResponse.md)

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

# **get_self_serve_plan_v1_self_serve_plan_get**
> SuccessEnvelopePlanResponse get_self_serve_plan_v1_self_serve_plan_get()

Get Self Serve Plan

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_plan_response import SuccessEnvelopePlanResponse
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
    api_instance = nexusrag_sdk.SelfServeApi(api_client)

    try:
        # Get Self Serve Plan
        api_response = api_instance.get_self_serve_plan_v1_self_serve_plan_get()
        print("The response of SelfServeApi->get_self_serve_plan_v1_self_serve_plan_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SelfServeApi->get_self_serve_plan_v1_self_serve_plan_get: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SuccessEnvelopePlanResponse**](SuccessEnvelopePlanResponse.md)

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

# **list_api_keys_v1_self_serve_api_keys_get**
> SuccessEnvelopeApiKeyListResponse list_api_keys_v1_self_serve_api_keys_get()

List Api Keys

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_api_key_list_response import SuccessEnvelopeApiKeyListResponse
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
    api_instance = nexusrag_sdk.SelfServeApi(api_client)

    try:
        # List Api Keys
        api_response = api_instance.list_api_keys_v1_self_serve_api_keys_get()
        print("The response of SelfServeApi->list_api_keys_v1_self_serve_api_keys_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SelfServeApi->list_api_keys_v1_self_serve_api_keys_get: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SuccessEnvelopeApiKeyListResponse**](SuccessEnvelopeApiKeyListResponse.md)

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

# **revoke_api_key_v1_self_serve_api_keys_key_id_revoke_post**
> SuccessEnvelopeApiKeyResponse revoke_api_key_v1_self_serve_api_keys_key_id_revoke_post(key_id, idempotency_key=idempotency_key)

Revoke Api Key

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_api_key_response import SuccessEnvelopeApiKeyResponse
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
    api_instance = nexusrag_sdk.SelfServeApi(api_client)
    key_id = 'key_id_example' # str | 
    idempotency_key = 'idempotency_key_example' # str |  (optional)

    try:
        # Revoke Api Key
        api_response = api_instance.revoke_api_key_v1_self_serve_api_keys_key_id_revoke_post(key_id, idempotency_key=idempotency_key)
        print("The response of SelfServeApi->revoke_api_key_v1_self_serve_api_keys_key_id_revoke_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SelfServeApi->revoke_api_key_v1_self_serve_api_keys_key_id_revoke_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **key_id** | **str**|  | 
 **idempotency_key** | **str**|  | [optional] 

### Return type

[**SuccessEnvelopeApiKeyResponse**](SuccessEnvelopeApiKeyResponse.md)

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

# **upgrade_plan_request_v1_self_serve_plan_upgrade_request_post**
> SuccessEnvelopePlanUpgradeResponse upgrade_plan_request_v1_self_serve_plan_upgrade_request_post(plan_upgrade_request_payload, idempotency_key=idempotency_key)

Upgrade Plan Request

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.plan_upgrade_request_payload import PlanUpgradeRequestPayload
from nexusrag_sdk.models.success_envelope_plan_upgrade_response import SuccessEnvelopePlanUpgradeResponse
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
    api_instance = nexusrag_sdk.SelfServeApi(api_client)
    plan_upgrade_request_payload = nexusrag_sdk.PlanUpgradeRequestPayload() # PlanUpgradeRequestPayload | 
    idempotency_key = 'idempotency_key_example' # str |  (optional)

    try:
        # Upgrade Plan Request
        api_response = api_instance.upgrade_plan_request_v1_self_serve_plan_upgrade_request_post(plan_upgrade_request_payload, idempotency_key=idempotency_key)
        print("The response of SelfServeApi->upgrade_plan_request_v1_self_serve_plan_upgrade_request_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SelfServeApi->upgrade_plan_request_v1_self_serve_plan_upgrade_request_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **plan_upgrade_request_payload** | [**PlanUpgradeRequestPayload**](PlanUpgradeRequestPayload.md)|  | 
 **idempotency_key** | **str**|  | [optional] 

### Return type

[**SuccessEnvelopePlanUpgradeResponse**](SuccessEnvelopePlanUpgradeResponse.md)

### Authorization

[BearerAuth](../README.md#BearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**202** | Successful Response |  -  |
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

# **usage_summary_v1_self_serve_usage_summary_get**
> NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse2 usage_summary_v1_self_serve_usage_summary_get(window_days=window_days)

Usage Summary

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.nexusrag_apps_api_response_success_envelope_usage_summary_response2 import NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse2
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
    api_instance = nexusrag_sdk.SelfServeApi(api_client)
    window_days = 30 # int |  (optional) (default to 30)

    try:
        # Usage Summary
        api_response = api_instance.usage_summary_v1_self_serve_usage_summary_get(window_days=window_days)
        print("The response of SelfServeApi->usage_summary_v1_self_serve_usage_summary_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SelfServeApi->usage_summary_v1_self_serve_usage_summary_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **window_days** | **int**|  | [optional] [default to 30]

### Return type

[**NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse2**](NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse2.md)

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

# **usage_timeseries_v1_self_serve_usage_timeseries_get**
> SuccessEnvelopeUsageTimeseriesResponse usage_timeseries_v1_self_serve_usage_timeseries_get(metric=metric, granularity=granularity, days=days)

Usage Timeseries

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_usage_timeseries_response import SuccessEnvelopeUsageTimeseriesResponse
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
    api_instance = nexusrag_sdk.SelfServeApi(api_client)
    metric = 'requests' # str |  (optional) (default to 'requests')
    granularity = 'day' # str |  (optional) (default to 'day')
    days = 30 # int |  (optional) (default to 30)

    try:
        # Usage Timeseries
        api_response = api_instance.usage_timeseries_v1_self_serve_usage_timeseries_get(metric=metric, granularity=granularity, days=days)
        print("The response of SelfServeApi->usage_timeseries_v1_self_serve_usage_timeseries_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SelfServeApi->usage_timeseries_v1_self_serve_usage_timeseries_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **metric** | **str**|  | [optional] [default to &#39;requests&#39;]
 **granularity** | **str**|  | [optional] [default to &#39;day&#39;]
 **days** | **int**|  | [optional] [default to 30]

### Return type

[**SuccessEnvelopeUsageTimeseriesResponse**](SuccessEnvelopeUsageTimeseriesResponse.md)

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

