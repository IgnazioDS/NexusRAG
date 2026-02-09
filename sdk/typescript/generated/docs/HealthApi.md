# HealthApi

All URIs are relative to *http://localhost:8000*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**healthV1HealthGet**](HealthApi.md#healthv1healthget) | **GET** /v1/health | Health |



## healthV1HealthGet

> SuccessEnvelopeHealthResponse healthV1HealthGet()

Health

### Example

```ts
import {
  Configuration,
  HealthApi,
} from 'nexusrag-sdk';
import type { HealthV1HealthGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const api = new HealthApi();

  try {
    const data = await api.healthV1HealthGet();
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

[**SuccessEnvelopeHealthResponse**](SuccessEnvelopeHealthResponse.md)

### Authorization

No authorization required

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

