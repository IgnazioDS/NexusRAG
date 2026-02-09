# nexusrag_sdk.AuditApi

All URIs are relative to *http://localhost:8000*

Method | HTTP request | Description
------------- | ------------- | -------------
[**get_audit_event_v1_audit_events_event_id_get**](AuditApi.md#get_audit_event_v1_audit_events_event_id_get) | **GET** /v1/audit/events/{event_id} | Get Audit Event
[**list_audit_events_v1_audit_events_get**](AuditApi.md#list_audit_events_v1_audit_events_get) | **GET** /v1/audit/events | List Audit Events


# **get_audit_event_v1_audit_events_event_id_get**
> SuccessEnvelopeAuditEventResponse get_audit_event_v1_audit_events_event_id_get(event_id)

Get Audit Event

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_audit_event_response import SuccessEnvelopeAuditEventResponse
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
    api_instance = nexusrag_sdk.AuditApi(api_client)
    event_id = 56 # int | 

    try:
        # Get Audit Event
        api_response = api_instance.get_audit_event_v1_audit_events_event_id_get(event_id)
        print("The response of AuditApi->get_audit_event_v1_audit_events_event_id_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuditApi->get_audit_event_v1_audit_events_event_id_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **event_id** | **int**|  | 

### Return type

[**SuccessEnvelopeAuditEventResponse**](SuccessEnvelopeAuditEventResponse.md)

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

# **list_audit_events_v1_audit_events_get**
> SuccessEnvelopeAuditEventsPage list_audit_events_v1_audit_events_get(tenant_id=tenant_id, event_type=event_type, outcome=outcome, resource_type=resource_type, resource_id=resource_id, var_from=var_from, to=to, offset=offset, limit=limit)

List Audit Events

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_audit_events_page import SuccessEnvelopeAuditEventsPage
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
    api_instance = nexusrag_sdk.AuditApi(api_client)
    tenant_id = 'tenant_id_example' # str |  (optional)
    event_type = 'event_type_example' # str |  (optional)
    outcome = 'outcome_example' # str |  (optional)
    resource_type = 'resource_type_example' # str |  (optional)
    resource_id = 'resource_id_example' # str |  (optional)
    var_from = '2013-10-20T19:20:30+01:00' # datetime |  (optional)
    to = '2013-10-20T19:20:30+01:00' # datetime |  (optional)
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Audit Events
        api_response = api_instance.list_audit_events_v1_audit_events_get(tenant_id=tenant_id, event_type=event_type, outcome=outcome, resource_type=resource_type, resource_id=resource_id, var_from=var_from, to=to, offset=offset, limit=limit)
        print("The response of AuditApi->list_audit_events_v1_audit_events_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuditApi->list_audit_events_v1_audit_events_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **tenant_id** | **str**|  | [optional] 
 **event_type** | **str**|  | [optional] 
 **outcome** | **str**|  | [optional] 
 **resource_type** | **str**|  | [optional] 
 **resource_id** | **str**|  | [optional] 
 **var_from** | **datetime**|  | [optional] 
 **to** | **datetime**|  | [optional] 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**SuccessEnvelopeAuditEventsPage**](SuccessEnvelopeAuditEventsPage.md)

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

