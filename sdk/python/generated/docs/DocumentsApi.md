# nexusrag_sdk.DocumentsApi

All URIs are relative to *http://localhost:8000*

Method | HTTP request | Description
------------- | ------------- | -------------
[**delete_document_v1_documents_document_id_delete**](DocumentsApi.md#delete_document_v1_documents_document_id_delete) | **DELETE** /v1/documents/{document_id} | Delete Document
[**get_document_v1_documents_document_id_get**](DocumentsApi.md#get_document_v1_documents_document_id_get) | **GET** /v1/documents/{document_id} | Get Document
[**ingest_text_document_v1_documents_text_post**](DocumentsApi.md#ingest_text_document_v1_documents_text_post) | **POST** /v1/documents/text | Ingest Text Document
[**list_documents_v1_documents_get**](DocumentsApi.md#list_documents_v1_documents_get) | **GET** /v1/documents | List Documents
[**reindex_document_v1_documents_document_id_reindex_post**](DocumentsApi.md#reindex_document_v1_documents_document_id_reindex_post) | **POST** /v1/documents/{document_id}/reindex | Reindex Document
[**upload_document_v1_documents_post**](DocumentsApi.md#upload_document_v1_documents_post) | **POST** /v1/documents | Upload Document


# **delete_document_v1_documents_document_id_delete**
> delete_document_v1_documents_document_id_delete(document_id, idempotency_key=idempotency_key)

Delete Document

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
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
    api_instance = nexusrag_sdk.DocumentsApi(api_client)
    document_id = 'document_id_example' # str | 
    idempotency_key = 'idempotency_key_example' # str |  (optional)

    try:
        # Delete Document
        api_instance.delete_document_v1_documents_document_id_delete(document_id, idempotency_key=idempotency_key)
    except Exception as e:
        print("Exception when calling DocumentsApi->delete_document_v1_documents_document_id_delete: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **document_id** | **str**|  | 
 **idempotency_key** | **str**|  | [optional] 

### Return type

void (empty response body)

### Authorization

[BearerAuth](../README.md#BearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
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

# **get_document_v1_documents_document_id_get**
> SuccessEnvelopeDocumentResponse get_document_v1_documents_document_id_get(document_id)

Get Document

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_document_response import SuccessEnvelopeDocumentResponse
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
    api_instance = nexusrag_sdk.DocumentsApi(api_client)
    document_id = 'document_id_example' # str | 

    try:
        # Get Document
        api_response = api_instance.get_document_v1_documents_document_id_get(document_id)
        print("The response of DocumentsApi->get_document_v1_documents_document_id_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling DocumentsApi->get_document_v1_documents_document_id_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **document_id** | **str**|  | 

### Return type

[**SuccessEnvelopeDocumentResponse**](SuccessEnvelopeDocumentResponse.md)

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

# **ingest_text_document_v1_documents_text_post**
> SuccessEnvelopeDocumentAccepted ingest_text_document_v1_documents_text_post(text_ingest_request, idempotency_key=idempotency_key)

Ingest Text Document

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_document_accepted import SuccessEnvelopeDocumentAccepted
from nexusrag_sdk.models.text_ingest_request import TextIngestRequest
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
    api_instance = nexusrag_sdk.DocumentsApi(api_client)
    text_ingest_request = nexusrag_sdk.TextIngestRequest() # TextIngestRequest | 
    idempotency_key = 'idempotency_key_example' # str |  (optional)

    try:
        # Ingest Text Document
        api_response = api_instance.ingest_text_document_v1_documents_text_post(text_ingest_request, idempotency_key=idempotency_key)
        print("The response of DocumentsApi->ingest_text_document_v1_documents_text_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling DocumentsApi->ingest_text_document_v1_documents_text_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **text_ingest_request** | [**TextIngestRequest**](TextIngestRequest.md)|  | 
 **idempotency_key** | **str**|  | [optional] 

### Return type

[**SuccessEnvelopeDocumentAccepted**](SuccessEnvelopeDocumentAccepted.md)

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

# **list_documents_v1_documents_get**
> SuccessEnvelopeListDocumentResponse list_documents_v1_documents_get(corpus_id=corpus_id)

List Documents

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_list_document_response import SuccessEnvelopeListDocumentResponse
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
    api_instance = nexusrag_sdk.DocumentsApi(api_client)
    corpus_id = 'corpus_id_example' # str |  (optional)

    try:
        # List Documents
        api_response = api_instance.list_documents_v1_documents_get(corpus_id=corpus_id)
        print("The response of DocumentsApi->list_documents_v1_documents_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling DocumentsApi->list_documents_v1_documents_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **corpus_id** | **str**|  | [optional] 

### Return type

[**SuccessEnvelopeListDocumentResponse**](SuccessEnvelopeListDocumentResponse.md)

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

# **reindex_document_v1_documents_document_id_reindex_post**
> SuccessEnvelopeDocumentAccepted reindex_document_v1_documents_document_id_reindex_post(document_id, idempotency_key=idempotency_key, reindex_request=reindex_request)

Reindex Document

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.reindex_request import ReindexRequest
from nexusrag_sdk.models.success_envelope_document_accepted import SuccessEnvelopeDocumentAccepted
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
    api_instance = nexusrag_sdk.DocumentsApi(api_client)
    document_id = 'document_id_example' # str | 
    idempotency_key = 'idempotency_key_example' # str |  (optional)
    reindex_request = nexusrag_sdk.ReindexRequest() # ReindexRequest |  (optional)

    try:
        # Reindex Document
        api_response = api_instance.reindex_document_v1_documents_document_id_reindex_post(document_id, idempotency_key=idempotency_key, reindex_request=reindex_request)
        print("The response of DocumentsApi->reindex_document_v1_documents_document_id_reindex_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling DocumentsApi->reindex_document_v1_documents_document_id_reindex_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **document_id** | **str**|  | 
 **idempotency_key** | **str**|  | [optional] 
 **reindex_request** | [**ReindexRequest**](ReindexRequest.md)|  | [optional] 

### Return type

[**SuccessEnvelopeDocumentAccepted**](SuccessEnvelopeDocumentAccepted.md)

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

# **upload_document_v1_documents_post**
> SuccessEnvelopeDocumentAccepted upload_document_v1_documents_post(corpus_id, file, idempotency_key=idempotency_key, document_id=document_id, overwrite=overwrite)

Upload Document

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_document_accepted import SuccessEnvelopeDocumentAccepted
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
    api_instance = nexusrag_sdk.DocumentsApi(api_client)
    corpus_id = 'corpus_id_example' # str | 
    file = None # bytearray | 
    idempotency_key = 'idempotency_key_example' # str |  (optional)
    document_id = 'document_id_example' # str |  (optional)
    overwrite = False # bool |  (optional) (default to False)

    try:
        # Upload Document
        api_response = api_instance.upload_document_v1_documents_post(corpus_id, file, idempotency_key=idempotency_key, document_id=document_id, overwrite=overwrite)
        print("The response of DocumentsApi->upload_document_v1_documents_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling DocumentsApi->upload_document_v1_documents_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **corpus_id** | **str**|  | 
 **file** | **bytearray**|  | 
 **idempotency_key** | **str**|  | [optional] 
 **document_id** | **str**|  | [optional] 
 **overwrite** | **bool**|  | [optional] [default to False]

### Return type

[**SuccessEnvelopeDocumentAccepted**](SuccessEnvelopeDocumentAccepted.md)

### Authorization

[BearerAuth](../README.md#BearerAuth)

### HTTP request headers

 - **Content-Type**: multipart/form-data
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

