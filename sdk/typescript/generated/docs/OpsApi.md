# OpsApi

All URIs are relative to *http://localhost:8000*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**opsHealthV1OpsHealthGet**](OpsApi.md#opshealthv1opshealthget) | **GET** /v1/ops/health | Ops Health |
| [**opsIngestionV1OpsIngestionGet**](OpsApi.md#opsingestionv1opsingestionget) | **GET** /v1/ops/ingestion | Ops Ingestion |
| [**opsMetricsV1OpsMetricsGet**](OpsApi.md#opsmetricsv1opsmetricsget) | **GET** /v1/ops/metrics | Ops Metrics |



## opsHealthV1OpsHealthGet

> SuccessEnvelopeDictStrAny opsHealthV1OpsHealthGet()

Ops Health

### Example

```ts
import {
  Configuration,
  OpsApi,
} from 'nexusrag-sdk';
import type { OpsHealthV1OpsHealthGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new OpsApi(config);

  try {
    const data = await api.opsHealthV1OpsHealthGet();
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

[**SuccessEnvelopeDictStrAny**](SuccessEnvelopeDictStrAny.md)

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


## opsIngestionV1OpsIngestionGet

> SuccessEnvelopeDictStrAny opsIngestionV1OpsIngestionGet(hours)

Ops Ingestion

### Example

```ts
import {
  Configuration,
  OpsApi,
} from 'nexusrag-sdk';
import type { OpsIngestionV1OpsIngestionGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new OpsApi(config);

  const body = {
    // number (optional)
    hours: 56,
  } satisfies OpsIngestionV1OpsIngestionGetRequest;

  try {
    const data = await api.opsIngestionV1OpsIngestionGet(body);
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
| **hours** | `number` |  | [Optional] [Defaults to `24`] |

### Return type

[**SuccessEnvelopeDictStrAny**](SuccessEnvelopeDictStrAny.md)

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


## opsMetricsV1OpsMetricsGet

> SuccessEnvelopeDictStrAny opsMetricsV1OpsMetricsGet()

Ops Metrics

### Example

```ts
import {
  Configuration,
  OpsApi,
} from 'nexusrag-sdk';
import type { OpsMetricsV1OpsMetricsGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new OpsApi(config);

  try {
    const data = await api.opsMetricsV1OpsMetricsGet();
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

[**SuccessEnvelopeDictStrAny**](SuccessEnvelopeDictStrAny.md)

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

