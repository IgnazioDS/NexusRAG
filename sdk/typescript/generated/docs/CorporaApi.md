# CorporaApi

All URIs are relative to *http://localhost:8000*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**getCorpusV1CorporaCorpusIdGet**](CorporaApi.md#getcorpusv1corporacorpusidget) | **GET** /v1/corpora/{corpus_id} | Get Corpus |
| [**listCorporaV1CorporaGet**](CorporaApi.md#listcorporav1corporaget) | **GET** /v1/corpora | List Corpora |
| [**patchCorpusV1CorporaCorpusIdPatch**](CorporaApi.md#patchcorpusv1corporacorpusidpatch) | **PATCH** /v1/corpora/{corpus_id} | Patch Corpus |



## getCorpusV1CorporaCorpusIdGet

> SuccessEnvelopeCorpusResponse getCorpusV1CorporaCorpusIdGet(corpusId)

Get Corpus

### Example

```ts
import {
  Configuration,
  CorporaApi,
} from 'nexusrag-sdk';
import type { GetCorpusV1CorporaCorpusIdGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new CorporaApi(config);

  const body = {
    // string
    corpusId: corpusId_example,
  } satisfies GetCorpusV1CorporaCorpusIdGetRequest;

  try {
    const data = await api.getCorpusV1CorporaCorpusIdGet(body);
    console.log(data);
  } catch (error) {
    console.error(error);
  }
}

// Run the test
example().catch(console.error);
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **corpusId** | `string` |  | [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopeCorpusResponse**](SuccessEnvelopeCorpusResponse.md)

### Authorization

[BearerAuth](../README.md#BearerAuth)

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: `application/json`


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful Response |  -  |
| **400** | Bad request |  -  |
| **401** | Unauthorized |  -  |
| **402** | Quota exceeded |  -  |
| **403** | Forbidden |  -  |
| **404** | Not found |  -  |
| **409** | Conflict |  -  |
| **422** | Validation error |  -  |
| **429** | Rate limited |  -  |
| **500** | Internal server error |  -  |
| **503** | Service unavailable |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


## listCorporaV1CorporaGet

> SuccessEnvelopeListCorpusResponse listCorporaV1CorporaGet()

List Corpora

### Example

```ts
import {
  Configuration,
  CorporaApi,
} from 'nexusrag-sdk';
import type { ListCorporaV1CorporaGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new CorporaApi(config);

  try {
    const data = await api.listCorporaV1CorporaGet();
    console.log(data);
  } catch (error) {
    console.error(error);
  }
}

// Run the test
example().catch(console.error);
```

### Parameters

This endpoint does not need any parameter.

### Return type

[**SuccessEnvelopeListCorpusResponse**](SuccessEnvelopeListCorpusResponse.md)

### Authorization

[BearerAuth](../README.md#BearerAuth)

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: `application/json`


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful Response |  -  |
| **400** | Bad request |  -  |
| **401** | Unauthorized |  -  |
| **402** | Quota exceeded |  -  |
| **403** | Forbidden |  -  |
| **404** | Not found |  -  |
| **409** | Conflict |  -  |
| **422** | Validation error |  -  |
| **429** | Rate limited |  -  |
| **500** | Internal server error |  -  |
| **503** | Service unavailable |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


## patchCorpusV1CorporaCorpusIdPatch

> SuccessEnvelopeCorpusResponse patchCorpusV1CorporaCorpusIdPatch(corpusId, corpusPatchRequest, idempotencyKey)

Patch Corpus

### Example

```ts
import {
  Configuration,
  CorporaApi,
} from 'nexusrag-sdk';
import type { PatchCorpusV1CorporaCorpusIdPatchRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new CorporaApi(config);

  const body = {
    // string
    corpusId: corpusId_example,
    // CorpusPatchRequest
    corpusPatchRequest: ...,
    // string (optional)
    idempotencyKey: idempotencyKey_example,
  } satisfies PatchCorpusV1CorporaCorpusIdPatchRequest;

  try {
    const data = await api.patchCorpusV1CorporaCorpusIdPatch(body);
    console.log(data);
  } catch (error) {
    console.error(error);
  }
}

// Run the test
example().catch(console.error);
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **corpusId** | `string` |  | [Defaults to `undefined`] |
| **corpusPatchRequest** | [CorpusPatchRequest](CorpusPatchRequest.md) |  | |
| **idempotencyKey** | `string` |  | [Optional] [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopeCorpusResponse**](SuccessEnvelopeCorpusResponse.md)

### Authorization

[BearerAuth](../README.md#BearerAuth)

### HTTP request headers

- **Content-Type**: `application/json`
- **Accept**: `application/json`


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful Response |  -  |
| **400** | Bad request |  -  |
| **401** | Unauthorized |  -  |
| **402** | Quota exceeded |  -  |
| **403** | Forbidden |  -  |
| **404** | Not found |  -  |
| **409** | Conflict |  -  |
| **422** | Validation error |  -  |
| **429** | Rate limited |  -  |
| **500** | Internal server error |  -  |
| **503** | Service unavailable |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)

