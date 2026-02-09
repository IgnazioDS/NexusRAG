# nexusrag_sdk.AdminApi

All URIs are relative to *http://localhost:8000*

Method | HTTP request | Description
------------- | ------------- | -------------
[**assign_tenant_plan_v1_admin_plans_tenant_id_patch**](AdminApi.md#assign_tenant_plan_v1_admin_plans_tenant_id_patch) | **PATCH** /v1/admin/plans/{tenant_id} | Assign Tenant Plan
[**get_quota_limits_v1_admin_quotas_tenant_id_get**](AdminApi.md#get_quota_limits_v1_admin_quotas_tenant_id_get) | **GET** /v1/admin/quotas/{tenant_id} | Get Quota Limits
[**get_tenant_plan_v1_admin_plans_tenant_id_get**](AdminApi.md#get_tenant_plan_v1_admin_plans_tenant_id_get) | **GET** /v1/admin/plans/{tenant_id} | Get Tenant Plan
[**get_usage_summary_v1_admin_usage_tenant_id_get**](AdminApi.md#get_usage_summary_v1_admin_usage_tenant_id_get) | **GET** /v1/admin/usage/{tenant_id} | Get Usage Summary
[**list_plans_v1_admin_plans_get**](AdminApi.md#list_plans_v1_admin_plans_get) | **GET** /v1/admin/plans | List Plans
[**patch_quota_limits_v1_admin_quotas_tenant_id_patch**](AdminApi.md#patch_quota_limits_v1_admin_quotas_tenant_id_patch) | **PATCH** /v1/admin/quotas/{tenant_id} | Patch Quota Limits
[**patch_tenant_overrides_v1_admin_plans_tenant_id_overrides_patch**](AdminApi.md#patch_tenant_overrides_v1_admin_plans_tenant_id_overrides_patch) | **PATCH** /v1/admin/plans/{tenant_id}/overrides | Patch Tenant Overrides


# **assign_tenant_plan_v1_admin_plans_tenant_id_patch**
> SuccessEnvelopeTenantPlanResponse assign_tenant_plan_v1_admin_plans_tenant_id_patch(tenant_id, plan_assignment_request, idempotency_key=idempotency_key)

Assign Tenant Plan

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.plan_assignment_request import PlanAssignmentRequest
from nexusrag_sdk.models.success_envelope_tenant_plan_response import SuccessEnvelopeTenantPlanResponse
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
    api_instance = nexusrag_sdk.AdminApi(api_client)
    tenant_id = 'tenant_id_example' # str | 
    plan_assignment_request = nexusrag_sdk.PlanAssignmentRequest() # PlanAssignmentRequest | 
    idempotency_key = 'idempotency_key_example' # str |  (optional)

    try:
        # Assign Tenant Plan
        api_response = api_instance.assign_tenant_plan_v1_admin_plans_tenant_id_patch(tenant_id, plan_assignment_request, idempotency_key=idempotency_key)
        print("The response of AdminApi->assign_tenant_plan_v1_admin_plans_tenant_id_patch:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AdminApi->assign_tenant_plan_v1_admin_plans_tenant_id_patch: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **tenant_id** | **str**|  | 
 **plan_assignment_request** | [**PlanAssignmentRequest**](PlanAssignmentRequest.md)|  | 
 **idempotency_key** | **str**|  | [optional] 

### Return type

[**SuccessEnvelopeTenantPlanResponse**](SuccessEnvelopeTenantPlanResponse.md)

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

# **get_quota_limits_v1_admin_quotas_tenant_id_get**
> SuccessEnvelopePlanLimitResponse get_quota_limits_v1_admin_quotas_tenant_id_get(tenant_id)

Get Quota Limits

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_plan_limit_response import SuccessEnvelopePlanLimitResponse
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
    api_instance = nexusrag_sdk.AdminApi(api_client)
    tenant_id = 'tenant_id_example' # str | 

    try:
        # Get Quota Limits
        api_response = api_instance.get_quota_limits_v1_admin_quotas_tenant_id_get(tenant_id)
        print("The response of AdminApi->get_quota_limits_v1_admin_quotas_tenant_id_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AdminApi->get_quota_limits_v1_admin_quotas_tenant_id_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **tenant_id** | **str**|  | 

### Return type

[**SuccessEnvelopePlanLimitResponse**](SuccessEnvelopePlanLimitResponse.md)

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

# **get_tenant_plan_v1_admin_plans_tenant_id_get**
> SuccessEnvelopeTenantPlanResponse get_tenant_plan_v1_admin_plans_tenant_id_get(tenant_id)

Get Tenant Plan

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_tenant_plan_response import SuccessEnvelopeTenantPlanResponse
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
    api_instance = nexusrag_sdk.AdminApi(api_client)
    tenant_id = 'tenant_id_example' # str | 

    try:
        # Get Tenant Plan
        api_response = api_instance.get_tenant_plan_v1_admin_plans_tenant_id_get(tenant_id)
        print("The response of AdminApi->get_tenant_plan_v1_admin_plans_tenant_id_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AdminApi->get_tenant_plan_v1_admin_plans_tenant_id_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **tenant_id** | **str**|  | 

### Return type

[**SuccessEnvelopeTenantPlanResponse**](SuccessEnvelopeTenantPlanResponse.md)

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

# **get_usage_summary_v1_admin_usage_tenant_id_get**
> NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse1 get_usage_summary_v1_admin_usage_tenant_id_get(tenant_id, start, period=period)

Get Usage Summary

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.nexusrag_apps_api_response_success_envelope_usage_summary_response1 import NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse1
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
    api_instance = nexusrag_sdk.AdminApi(api_client)
    tenant_id = 'tenant_id_example' # str | 
    start = '2013-10-20' # date | 
    period = 'day' # str |  (optional) (default to 'day')

    try:
        # Get Usage Summary
        api_response = api_instance.get_usage_summary_v1_admin_usage_tenant_id_get(tenant_id, start, period=period)
        print("The response of AdminApi->get_usage_summary_v1_admin_usage_tenant_id_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AdminApi->get_usage_summary_v1_admin_usage_tenant_id_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **tenant_id** | **str**|  | 
 **start** | **date**|  | 
 **period** | **str**|  | [optional] [default to &#39;day&#39;]

### Return type

[**NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse1**](NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse1.md)

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

# **list_plans_v1_admin_plans_get**
> SuccessEnvelopeListPlanResponse list_plans_v1_admin_plans_get()

List Plans

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_list_plan_response import SuccessEnvelopeListPlanResponse
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
    api_instance = nexusrag_sdk.AdminApi(api_client)

    try:
        # List Plans
        api_response = api_instance.list_plans_v1_admin_plans_get()
        print("The response of AdminApi->list_plans_v1_admin_plans_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AdminApi->list_plans_v1_admin_plans_get: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SuccessEnvelopeListPlanResponse**](SuccessEnvelopeListPlanResponse.md)

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

# **patch_quota_limits_v1_admin_quotas_tenant_id_patch**
> SuccessEnvelopePlanLimitResponse patch_quota_limits_v1_admin_quotas_tenant_id_patch(tenant_id, plan_limit_patch_request, idempotency_key=idempotency_key)

Patch Quota Limits

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.plan_limit_patch_request import PlanLimitPatchRequest
from nexusrag_sdk.models.success_envelope_plan_limit_response import SuccessEnvelopePlanLimitResponse
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
    api_instance = nexusrag_sdk.AdminApi(api_client)
    tenant_id = 'tenant_id_example' # str | 
    plan_limit_patch_request = nexusrag_sdk.PlanLimitPatchRequest() # PlanLimitPatchRequest | 
    idempotency_key = 'idempotency_key_example' # str |  (optional)

    try:
        # Patch Quota Limits
        api_response = api_instance.patch_quota_limits_v1_admin_quotas_tenant_id_patch(tenant_id, plan_limit_patch_request, idempotency_key=idempotency_key)
        print("The response of AdminApi->patch_quota_limits_v1_admin_quotas_tenant_id_patch:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AdminApi->patch_quota_limits_v1_admin_quotas_tenant_id_patch: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **tenant_id** | **str**|  | 
 **plan_limit_patch_request** | [**PlanLimitPatchRequest**](PlanLimitPatchRequest.md)|  | 
 **idempotency_key** | **str**|  | [optional] 

### Return type

[**SuccessEnvelopePlanLimitResponse**](SuccessEnvelopePlanLimitResponse.md)

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

# **patch_tenant_overrides_v1_admin_plans_tenant_id_overrides_patch**
> SuccessEnvelopeTenantPlanResponse patch_tenant_overrides_v1_admin_plans_tenant_id_overrides_patch(tenant_id, feature_override_request, idempotency_key=idempotency_key)

Patch Tenant Overrides

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.feature_override_request import FeatureOverrideRequest
from nexusrag_sdk.models.success_envelope_tenant_plan_response import SuccessEnvelopeTenantPlanResponse
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
    api_instance = nexusrag_sdk.AdminApi(api_client)
    tenant_id = 'tenant_id_example' # str | 
    feature_override_request = nexusrag_sdk.FeatureOverrideRequest() # FeatureOverrideRequest | 
    idempotency_key = 'idempotency_key_example' # str |  (optional)

    try:
        # Patch Tenant Overrides
        api_response = api_instance.patch_tenant_overrides_v1_admin_plans_tenant_id_overrides_patch(tenant_id, feature_override_request, idempotency_key=idempotency_key)
        print("The response of AdminApi->patch_tenant_overrides_v1_admin_plans_tenant_id_overrides_patch:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AdminApi->patch_tenant_overrides_v1_admin_plans_tenant_id_overrides_patch: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **tenant_id** | **str**|  | 
 **feature_override_request** | [**FeatureOverrideRequest**](FeatureOverrideRequest.md)|  | 
 **idempotency_key** | **str**|  | [optional] 

### Return type

[**SuccessEnvelopeTenantPlanResponse**](SuccessEnvelopeTenantPlanResponse.md)

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

