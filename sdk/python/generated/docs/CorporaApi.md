# nexusrag_sdk.CorporaApi

All URIs are relative to *http://localhost:8000*

Method | HTTP request | Description
------------- | ------------- | -------------
[**get_corpus_v1_corpora_corpus_id_get**](CorporaApi.md#get_corpus_v1_corpora_corpus_id_get) | **GET** /v1/corpora/{corpus_id} | Get Corpus
[**list_corpora_v1_corpora_get**](CorporaApi.md#list_corpora_v1_corpora_get) | **GET** /v1/corpora | List Corpora
[**patch_corpus_v1_corpora_corpus_id_patch**](CorporaApi.md#patch_corpus_v1_corpora_corpus_id_patch) | **PATCH** /v1/corpora/{corpus_id} | Patch Corpus


# **get_corpus_v1_corpora_corpus_id_get**
> SuccessEnvelopeCorpusResponse get_corpus_v1_corpora_corpus_id_get(corpus_id)

Get Corpus

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_corpus_response import SuccessEnvelopeCorpusResponse
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
    api_instance = nexusrag_sdk.CorporaApi(api_client)
    corpus_id = 'corpus_id_example' # str | 

    try:
        # Get Corpus
        api_response = api_instance.get_corpus_v1_corpora_corpus_id_get(corpus_id)
        print("The response of CorporaApi->get_corpus_v1_corpora_corpus_id_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling CorporaApi->get_corpus_v1_corpora_corpus_id_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **corpus_id** | **str**|  | 

### Return type

[**SuccessEnvelopeCorpusResponse**](SuccessEnvelopeCorpusResponse.md)

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

# **list_corpora_v1_corpora_get**
> SuccessEnvelopeListCorpusResponse list_corpora_v1_corpora_get()

List Corpora

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.success_envelope_list_corpus_response import SuccessEnvelopeListCorpusResponse
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
    api_instance = nexusrag_sdk.CorporaApi(api_client)

    try:
        # List Corpora
        api_response = api_instance.list_corpora_v1_corpora_get()
        print("The response of CorporaApi->list_corpora_v1_corpora_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling CorporaApi->list_corpora_v1_corpora_get: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SuccessEnvelopeListCorpusResponse**](SuccessEnvelopeListCorpusResponse.md)

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

# **patch_corpus_v1_corpora_corpus_id_patch**
> SuccessEnvelopeCorpusResponse patch_corpus_v1_corpora_corpus_id_patch(corpus_id, corpus_patch_request, idempotency_key=idempotency_key)

Patch Corpus

### Example

* Bearer Authentication (BearerAuth):

```python
import nexusrag_sdk
from nexusrag_sdk.models.corpus_patch_request import CorpusPatchRequest
from nexusrag_sdk.models.success_envelope_corpus_response import SuccessEnvelopeCorpusResponse
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
    api_instance = nexusrag_sdk.CorporaApi(api_client)
    corpus_id = 'corpus_id_example' # str | 
    corpus_patch_request = nexusrag_sdk.CorpusPatchRequest() # CorpusPatchRequest | 
    idempotency_key = 'idempotency_key_example' # str |  (optional)

    try:
        # Patch Corpus
        api_response = api_instance.patch_corpus_v1_corpora_corpus_id_patch(corpus_id, corpus_patch_request, idempotency_key=idempotency_key)
        print("The response of CorporaApi->patch_corpus_v1_corpora_corpus_id_patch:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling CorporaApi->patch_corpus_v1_corpora_corpus_id_patch: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **corpus_id** | **str**|  | 
 **corpus_patch_request** | [**CorpusPatchRequest**](CorpusPatchRequest.md)|  | 
 **idempotency_key** | **str**|  | [optional] 

### Return type

[**SuccessEnvelopeCorpusResponse**](SuccessEnvelopeCorpusResponse.md)

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

