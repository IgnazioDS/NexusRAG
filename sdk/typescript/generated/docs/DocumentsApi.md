# DocumentsApi

All URIs are relative to *http://localhost:8000*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**deleteDocumentV1DocumentsDocumentIdDelete**](DocumentsApi.md#deletedocumentv1documentsdocumentiddelete) | **DELETE** /v1/documents/{document_id} | Delete Document |
| [**getDocumentV1DocumentsDocumentIdGet**](DocumentsApi.md#getdocumentv1documentsdocumentidget) | **GET** /v1/documents/{document_id} | Get Document |
| [**ingestTextDocumentV1DocumentsTextPost**](DocumentsApi.md#ingesttextdocumentv1documentstextpost) | **POST** /v1/documents/text | Ingest Text Document |
| [**listDocumentsV1DocumentsGet**](DocumentsApi.md#listdocumentsv1documentsget) | **GET** /v1/documents | List Documents |
| [**reindexDocumentV1DocumentsDocumentIdReindexPost**](DocumentsApi.md#reindexdocumentv1documentsdocumentidreindexpost) | **POST** /v1/documents/{document_id}/reindex | Reindex Document |
| [**uploadDocumentV1DocumentsPost**](DocumentsApi.md#uploaddocumentv1documentspost) | **POST** /v1/documents | Upload Document |



## deleteDocumentV1DocumentsDocumentIdDelete

> deleteDocumentV1DocumentsDocumentIdDelete(documentId, idempotencyKey)

Delete Document

### Example

```ts
import {
  Configuration,
  DocumentsApi,
} from 'nexusrag-sdk';
import type { DeleteDocumentV1DocumentsDocumentIdDeleteRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new DocumentsApi(config);

  const body = {
    // string
    documentId: documentId_example,
    // string (optional)
    idempotencyKey: idempotencyKey_example,
  } satisfies DeleteDocumentV1DocumentsDocumentIdDeleteRequest;

  try {
    const data = await api.deleteDocumentV1DocumentsDocumentIdDelete(body);
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
| **documentId** | `string` |  | [Defaults to `undefined`] |
| **idempotencyKey** | `string` |  | [Optional] [Defaults to `undefined`] |

### Return type

`void` (Empty response body)

### Authorization

[BearerAuth](../README.md#BearerAuth)

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: `application/json`


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **204** | Successful Response |  -  |
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


## getDocumentV1DocumentsDocumentIdGet

> SuccessEnvelopeDocumentResponse getDocumentV1DocumentsDocumentIdGet(documentId)

Get Document

### Example

```ts
import {
  Configuration,
  DocumentsApi,
} from 'nexusrag-sdk';
import type { GetDocumentV1DocumentsDocumentIdGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new DocumentsApi(config);

  const body = {
    // string
    documentId: documentId_example,
  } satisfies GetDocumentV1DocumentsDocumentIdGetRequest;

  try {
    const data = await api.getDocumentV1DocumentsDocumentIdGet(body);
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
| **documentId** | `string` |  | [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopeDocumentResponse**](SuccessEnvelopeDocumentResponse.md)

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


## ingestTextDocumentV1DocumentsTextPost

> SuccessEnvelopeDocumentAccepted ingestTextDocumentV1DocumentsTextPost(textIngestRequest, idempotencyKey)

Ingest Text Document

### Example

```ts
import {
  Configuration,
  DocumentsApi,
} from 'nexusrag-sdk';
import type { IngestTextDocumentV1DocumentsTextPostRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new DocumentsApi(config);

  const body = {
    // TextIngestRequest
    textIngestRequest: ...,
    // string (optional)
    idempotencyKey: idempotencyKey_example,
  } satisfies IngestTextDocumentV1DocumentsTextPostRequest;

  try {
    const data = await api.ingestTextDocumentV1DocumentsTextPost(body);
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
| **textIngestRequest** | [TextIngestRequest](TextIngestRequest.md) |  | |
| **idempotencyKey** | `string` |  | [Optional] [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopeDocumentAccepted**](SuccessEnvelopeDocumentAccepted.md)

### Authorization

[BearerAuth](../README.md#BearerAuth)

### HTTP request headers

- **Content-Type**: `application/json`
- **Accept**: `application/json`


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **202** | Successful Response |  -  |
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


## listDocumentsV1DocumentsGet

> SuccessEnvelopeListDocumentResponse listDocumentsV1DocumentsGet(corpusId)

List Documents

### Example

```ts
import {
  Configuration,
  DocumentsApi,
} from 'nexusrag-sdk';
import type { ListDocumentsV1DocumentsGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new DocumentsApi(config);

  const body = {
    // string (optional)
    corpusId: corpusId_example,
  } satisfies ListDocumentsV1DocumentsGetRequest;

  try {
    const data = await api.listDocumentsV1DocumentsGet(body);
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
| **corpusId** | `string` |  | [Optional] [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopeListDocumentResponse**](SuccessEnvelopeListDocumentResponse.md)

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


## reindexDocumentV1DocumentsDocumentIdReindexPost

> SuccessEnvelopeDocumentAccepted reindexDocumentV1DocumentsDocumentIdReindexPost(documentId, idempotencyKey, reindexRequest)

Reindex Document

### Example

```ts
import {
  Configuration,
  DocumentsApi,
} from 'nexusrag-sdk';
import type { ReindexDocumentV1DocumentsDocumentIdReindexPostRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new DocumentsApi(config);

  const body = {
    // string
    documentId: documentId_example,
    // string (optional)
    idempotencyKey: idempotencyKey_example,
    // ReindexRequest (optional)
    reindexRequest: ...,
  } satisfies ReindexDocumentV1DocumentsDocumentIdReindexPostRequest;

  try {
    const data = await api.reindexDocumentV1DocumentsDocumentIdReindexPost(body);
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
| **documentId** | `string` |  | [Defaults to `undefined`] |
| **idempotencyKey** | `string` |  | [Optional] [Defaults to `undefined`] |
| **reindexRequest** | [ReindexRequest](ReindexRequest.md) |  | [Optional] |

### Return type

[**SuccessEnvelopeDocumentAccepted**](SuccessEnvelopeDocumentAccepted.md)

### Authorization

[BearerAuth](../README.md#BearerAuth)

### HTTP request headers

- **Content-Type**: `application/json`
- **Accept**: `application/json`


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **202** | Successful Response |  -  |
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


## uploadDocumentV1DocumentsPost

> SuccessEnvelopeDocumentAccepted uploadDocumentV1DocumentsPost(corpusId, file, idempotencyKey, documentId, overwrite)

Upload Document

### Example

```ts
import {
  Configuration,
  DocumentsApi,
} from 'nexusrag-sdk';
import type { UploadDocumentV1DocumentsPostRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new DocumentsApi(config);

  const body = {
    // string
    corpusId: corpusId_example,
    // Blob
    file: BINARY_DATA_HERE,
    // string (optional)
    idempotencyKey: idempotencyKey_example,
    // string (optional)
    documentId: documentId_example,
    // boolean (optional)
    overwrite: true,
  } satisfies UploadDocumentV1DocumentsPostRequest;

  try {
    const data = await api.uploadDocumentV1DocumentsPost(body);
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
| **file** | `Blob` |  | [Defaults to `undefined`] |
| **idempotencyKey** | `string` |  | [Optional] [Defaults to `undefined`] |
| **documentId** | `string` |  | [Optional] [Defaults to `undefined`] |
| **overwrite** | `boolean` |  | [Optional] [Defaults to `false`] |

### Return type

[**SuccessEnvelopeDocumentAccepted**](SuccessEnvelopeDocumentAccepted.md)

### Authorization

[BearerAuth](../README.md#BearerAuth)

### HTTP request headers

- **Content-Type**: `multipart/form-data`
- **Accept**: `application/json`


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **202** | Successful Response |  -  |
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

