# SelfServeApi

All URIs are relative to *http://localhost:8000*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**billingWebhookTestV1SelfServeBillingWebhookTestPost**](SelfServeApi.md#billingwebhooktestv1selfservebillingwebhooktestpost) | **POST** /v1/self-serve/billing/webhook-test | Billing Webhook Test |
| [**createApiKeyV1SelfServeApiKeysPost**](SelfServeApi.md#createapikeyv1selfserveapikeyspost) | **POST** /v1/self-serve/api-keys | Create Api Key |
| [**getSelfServePlanV1SelfServePlanGet**](SelfServeApi.md#getselfserveplanv1selfserveplanget) | **GET** /v1/self-serve/plan | Get Self Serve Plan |
| [**listApiKeysV1SelfServeApiKeysGet**](SelfServeApi.md#listapikeysv1selfserveapikeysget) | **GET** /v1/self-serve/api-keys | List Api Keys |
| [**revokeApiKeyV1SelfServeApiKeysKeyIdRevokePost**](SelfServeApi.md#revokeapikeyv1selfserveapikeyskeyidrevokepost) | **POST** /v1/self-serve/api-keys/{key_id}/revoke | Revoke Api Key |
| [**upgradePlanRequestV1SelfServePlanUpgradeRequestPost**](SelfServeApi.md#upgradeplanrequestv1selfserveplanupgraderequestpost) | **POST** /v1/self-serve/plan/upgrade-request | Upgrade Plan Request |
| [**usageSummaryV1SelfServeUsageSummaryGet**](SelfServeApi.md#usagesummaryv1selfserveusagesummaryget) | **GET** /v1/self-serve/usage/summary | Usage Summary |
| [**usageTimeseriesV1SelfServeUsageTimeseriesGet**](SelfServeApi.md#usagetimeseriesv1selfserveusagetimeseriesget) | **GET** /v1/self-serve/usage/timeseries | Usage Timeseries |



## billingWebhookTestV1SelfServeBillingWebhookTestPost

> SuccessEnvelopeBillingWebhookTestResponse billingWebhookTestV1SelfServeBillingWebhookTestPost()

Billing Webhook Test

### Example

```ts
import {
  Configuration,
  SelfServeApi,
} from 'nexusrag-sdk';
import type { BillingWebhookTestV1SelfServeBillingWebhookTestPostRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new SelfServeApi(config);

  try {
    const data = await api.billingWebhookTestV1SelfServeBillingWebhookTestPost();
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

[**SuccessEnvelopeBillingWebhookTestResponse**](SuccessEnvelopeBillingWebhookTestResponse.md)

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


## createApiKeyV1SelfServeApiKeysPost

> SuccessEnvelopeApiKeyCreateResponse createApiKeyV1SelfServeApiKeysPost(apiKeyCreateRequest, idempotencyKey)

Create Api Key

### Example

```ts
import {
  Configuration,
  SelfServeApi,
} from 'nexusrag-sdk';
import type { CreateApiKeyV1SelfServeApiKeysPostRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new SelfServeApi(config);

  const body = {
    // ApiKeyCreateRequest
    apiKeyCreateRequest: ...,
    // string (optional)
    idempotencyKey: idempotencyKey_example,
  } satisfies CreateApiKeyV1SelfServeApiKeysPostRequest;

  try {
    const data = await api.createApiKeyV1SelfServeApiKeysPost(body);
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
| **apiKeyCreateRequest** | [ApiKeyCreateRequest](ApiKeyCreateRequest.md) |  | |
| **idempotencyKey** | `string` |  | [Optional] [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopeApiKeyCreateResponse**](SuccessEnvelopeApiKeyCreateResponse.md)

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


## getSelfServePlanV1SelfServePlanGet

> SuccessEnvelopePlanResponse getSelfServePlanV1SelfServePlanGet()

Get Self Serve Plan

### Example

```ts
import {
  Configuration,
  SelfServeApi,
} from 'nexusrag-sdk';
import type { GetSelfServePlanV1SelfServePlanGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new SelfServeApi(config);

  try {
    const data = await api.getSelfServePlanV1SelfServePlanGet();
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

[**SuccessEnvelopePlanResponse**](SuccessEnvelopePlanResponse.md)

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


## listApiKeysV1SelfServeApiKeysGet

> SuccessEnvelopeApiKeyListResponse listApiKeysV1SelfServeApiKeysGet()

List Api Keys

### Example

```ts
import {
  Configuration,
  SelfServeApi,
} from 'nexusrag-sdk';
import type { ListApiKeysV1SelfServeApiKeysGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new SelfServeApi(config);

  try {
    const data = await api.listApiKeysV1SelfServeApiKeysGet();
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

[**SuccessEnvelopeApiKeyListResponse**](SuccessEnvelopeApiKeyListResponse.md)

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


## revokeApiKeyV1SelfServeApiKeysKeyIdRevokePost

> SuccessEnvelopeApiKeyResponse revokeApiKeyV1SelfServeApiKeysKeyIdRevokePost(keyId, idempotencyKey)

Revoke Api Key

### Example

```ts
import {
  Configuration,
  SelfServeApi,
} from 'nexusrag-sdk';
import type { RevokeApiKeyV1SelfServeApiKeysKeyIdRevokePostRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new SelfServeApi(config);

  const body = {
    // string
    keyId: keyId_example,
    // string (optional)
    idempotencyKey: idempotencyKey_example,
  } satisfies RevokeApiKeyV1SelfServeApiKeysKeyIdRevokePostRequest;

  try {
    const data = await api.revokeApiKeyV1SelfServeApiKeysKeyIdRevokePost(body);
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
| **keyId** | `string` |  | [Defaults to `undefined`] |
| **idempotencyKey** | `string` |  | [Optional] [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopeApiKeyResponse**](SuccessEnvelopeApiKeyResponse.md)

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


## upgradePlanRequestV1SelfServePlanUpgradeRequestPost

> SuccessEnvelopePlanUpgradeResponse upgradePlanRequestV1SelfServePlanUpgradeRequestPost(planUpgradeRequestPayload, idempotencyKey)

Upgrade Plan Request

### Example

```ts
import {
  Configuration,
  SelfServeApi,
} from 'nexusrag-sdk';
import type { UpgradePlanRequestV1SelfServePlanUpgradeRequestPostRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new SelfServeApi(config);

  const body = {
    // PlanUpgradeRequestPayload
    planUpgradeRequestPayload: ...,
    // string (optional)
    idempotencyKey: idempotencyKey_example,
  } satisfies UpgradePlanRequestV1SelfServePlanUpgradeRequestPostRequest;

  try {
    const data = await api.upgradePlanRequestV1SelfServePlanUpgradeRequestPost(body);
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
| **planUpgradeRequestPayload** | [PlanUpgradeRequestPayload](PlanUpgradeRequestPayload.md) |  | |
| **idempotencyKey** | `string` |  | [Optional] [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopePlanUpgradeResponse**](SuccessEnvelopePlanUpgradeResponse.md)

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


## usageSummaryV1SelfServeUsageSummaryGet

> NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse2 usageSummaryV1SelfServeUsageSummaryGet(windowDays)

Usage Summary

### Example

```ts
import {
  Configuration,
  SelfServeApi,
} from 'nexusrag-sdk';
import type { UsageSummaryV1SelfServeUsageSummaryGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new SelfServeApi(config);

  const body = {
    // number (optional)
    windowDays: 56,
  } satisfies UsageSummaryV1SelfServeUsageSummaryGetRequest;

  try {
    const data = await api.usageSummaryV1SelfServeUsageSummaryGet(body);
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
| **windowDays** | `number` |  | [Optional] [Defaults to `30`] |

### Return type

[**NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse2**](NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse2.md)

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


## usageTimeseriesV1SelfServeUsageTimeseriesGet

> SuccessEnvelopeUsageTimeseriesResponse usageTimeseriesV1SelfServeUsageTimeseriesGet(metric, granularity, days)

Usage Timeseries

### Example

```ts
import {
  Configuration,
  SelfServeApi,
} from 'nexusrag-sdk';
import type { UsageTimeseriesV1SelfServeUsageTimeseriesGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new SelfServeApi(config);

  const body = {
    // string (optional)
    metric: metric_example,
    // string (optional)
    granularity: granularity_example,
    // number (optional)
    days: 56,
  } satisfies UsageTimeseriesV1SelfServeUsageTimeseriesGetRequest;

  try {
    const data = await api.usageTimeseriesV1SelfServeUsageTimeseriesGet(body);
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
| **metric** | `string` |  | [Optional] [Defaults to `&#39;requests&#39;`] |
| **granularity** | `string` |  | [Optional] [Defaults to `&#39;day&#39;`] |
| **days** | `number` |  | [Optional] [Defaults to `30`] |

### Return type

[**SuccessEnvelopeUsageTimeseriesResponse**](SuccessEnvelopeUsageTimeseriesResponse.md)

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

