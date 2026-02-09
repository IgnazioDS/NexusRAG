# AdminApi

All URIs are relative to *http://localhost:8000*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**assignTenantPlanV1AdminPlansTenantIdPatch**](AdminApi.md#assigntenantplanv1adminplanstenantidpatch) | **PATCH** /v1/admin/plans/{tenant_id} | Assign Tenant Plan |
| [**getQuotaLimitsV1AdminQuotasTenantIdGet**](AdminApi.md#getquotalimitsv1adminquotastenantidget) | **GET** /v1/admin/quotas/{tenant_id} | Get Quota Limits |
| [**getTenantPlanV1AdminPlansTenantIdGet**](AdminApi.md#gettenantplanv1adminplanstenantidget) | **GET** /v1/admin/plans/{tenant_id} | Get Tenant Plan |
| [**getUsageSummaryV1AdminUsageTenantIdGet**](AdminApi.md#getusagesummaryv1adminusagetenantidget) | **GET** /v1/admin/usage/{tenant_id} | Get Usage Summary |
| [**listPlansV1AdminPlansGet**](AdminApi.md#listplansv1adminplansget) | **GET** /v1/admin/plans | List Plans |
| [**patchQuotaLimitsV1AdminQuotasTenantIdPatch**](AdminApi.md#patchquotalimitsv1adminquotastenantidpatch) | **PATCH** /v1/admin/quotas/{tenant_id} | Patch Quota Limits |
| [**patchTenantOverridesV1AdminPlansTenantIdOverridesPatch**](AdminApi.md#patchtenantoverridesv1adminplanstenantidoverridespatch) | **PATCH** /v1/admin/plans/{tenant_id}/overrides | Patch Tenant Overrides |



## assignTenantPlanV1AdminPlansTenantIdPatch

> SuccessEnvelopeTenantPlanResponse assignTenantPlanV1AdminPlansTenantIdPatch(tenantId, planAssignmentRequest, idempotencyKey)

Assign Tenant Plan

### Example

```ts
import {
  Configuration,
  AdminApi,
} from 'nexusrag-sdk';
import type { AssignTenantPlanV1AdminPlansTenantIdPatchRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new AdminApi(config);

  const body = {
    // string
    tenantId: tenantId_example,
    // PlanAssignmentRequest
    planAssignmentRequest: ...,
    // string (optional)
    idempotencyKey: idempotencyKey_example,
  } satisfies AssignTenantPlanV1AdminPlansTenantIdPatchRequest;

  try {
    const data = await api.assignTenantPlanV1AdminPlansTenantIdPatch(body);
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
| **tenantId** | `string` |  | [Defaults to `undefined`] |
| **planAssignmentRequest** | [PlanAssignmentRequest](PlanAssignmentRequest.md) |  | |
| **idempotencyKey** | `string` |  | [Optional] [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopeTenantPlanResponse**](SuccessEnvelopeTenantPlanResponse.md)

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


## getQuotaLimitsV1AdminQuotasTenantIdGet

> SuccessEnvelopePlanLimitResponse getQuotaLimitsV1AdminQuotasTenantIdGet(tenantId)

Get Quota Limits

### Example

```ts
import {
  Configuration,
  AdminApi,
} from 'nexusrag-sdk';
import type { GetQuotaLimitsV1AdminQuotasTenantIdGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new AdminApi(config);

  const body = {
    // string
    tenantId: tenantId_example,
  } satisfies GetQuotaLimitsV1AdminQuotasTenantIdGetRequest;

  try {
    const data = await api.getQuotaLimitsV1AdminQuotasTenantIdGet(body);
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
| **tenantId** | `string` |  | [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopePlanLimitResponse**](SuccessEnvelopePlanLimitResponse.md)

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


## getTenantPlanV1AdminPlansTenantIdGet

> SuccessEnvelopeTenantPlanResponse getTenantPlanV1AdminPlansTenantIdGet(tenantId)

Get Tenant Plan

### Example

```ts
import {
  Configuration,
  AdminApi,
} from 'nexusrag-sdk';
import type { GetTenantPlanV1AdminPlansTenantIdGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new AdminApi(config);

  const body = {
    // string
    tenantId: tenantId_example,
  } satisfies GetTenantPlanV1AdminPlansTenantIdGetRequest;

  try {
    const data = await api.getTenantPlanV1AdminPlansTenantIdGet(body);
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
| **tenantId** | `string` |  | [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopeTenantPlanResponse**](SuccessEnvelopeTenantPlanResponse.md)

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


## getUsageSummaryV1AdminUsageTenantIdGet

> NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse1 getUsageSummaryV1AdminUsageTenantIdGet(tenantId, start, period)

Get Usage Summary

### Example

```ts
import {
  Configuration,
  AdminApi,
} from 'nexusrag-sdk';
import type { GetUsageSummaryV1AdminUsageTenantIdGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new AdminApi(config);

  const body = {
    // string
    tenantId: tenantId_example,
    // Date
    start: 2013-10-20,
    // string (optional)
    period: period_example,
  } satisfies GetUsageSummaryV1AdminUsageTenantIdGetRequest;

  try {
    const data = await api.getUsageSummaryV1AdminUsageTenantIdGet(body);
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
| **tenantId** | `string` |  | [Defaults to `undefined`] |
| **start** | `Date` |  | [Defaults to `undefined`] |
| **period** | `string` |  | [Optional] [Defaults to `&#39;day&#39;`] |

### Return type

[**NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse1**](NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse1.md)

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


## listPlansV1AdminPlansGet

> SuccessEnvelopeListPlanResponse listPlansV1AdminPlansGet()

List Plans

### Example

```ts
import {
  Configuration,
  AdminApi,
} from 'nexusrag-sdk';
import type { ListPlansV1AdminPlansGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new AdminApi(config);

  try {
    const data = await api.listPlansV1AdminPlansGet();
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

[**SuccessEnvelopeListPlanResponse**](SuccessEnvelopeListPlanResponse.md)

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


## patchQuotaLimitsV1AdminQuotasTenantIdPatch

> SuccessEnvelopePlanLimitResponse patchQuotaLimitsV1AdminQuotasTenantIdPatch(tenantId, planLimitPatchRequest, idempotencyKey)

Patch Quota Limits

### Example

```ts
import {
  Configuration,
  AdminApi,
} from 'nexusrag-sdk';
import type { PatchQuotaLimitsV1AdminQuotasTenantIdPatchRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new AdminApi(config);

  const body = {
    // string
    tenantId: tenantId_example,
    // PlanLimitPatchRequest
    planLimitPatchRequest: ...,
    // string (optional)
    idempotencyKey: idempotencyKey_example,
  } satisfies PatchQuotaLimitsV1AdminQuotasTenantIdPatchRequest;

  try {
    const data = await api.patchQuotaLimitsV1AdminQuotasTenantIdPatch(body);
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
| **tenantId** | `string` |  | [Defaults to `undefined`] |
| **planLimitPatchRequest** | [PlanLimitPatchRequest](PlanLimitPatchRequest.md) |  | |
| **idempotencyKey** | `string` |  | [Optional] [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopePlanLimitResponse**](SuccessEnvelopePlanLimitResponse.md)

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


## patchTenantOverridesV1AdminPlansTenantIdOverridesPatch

> SuccessEnvelopeTenantPlanResponse patchTenantOverridesV1AdminPlansTenantIdOverridesPatch(tenantId, featureOverrideRequest, idempotencyKey)

Patch Tenant Overrides

### Example

```ts
import {
  Configuration,
  AdminApi,
} from 'nexusrag-sdk';
import type { PatchTenantOverridesV1AdminPlansTenantIdOverridesPatchRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new AdminApi(config);

  const body = {
    // string
    tenantId: tenantId_example,
    // FeatureOverrideRequest
    featureOverrideRequest: ...,
    // string (optional)
    idempotencyKey: idempotencyKey_example,
  } satisfies PatchTenantOverridesV1AdminPlansTenantIdOverridesPatchRequest;

  try {
    const data = await api.patchTenantOverridesV1AdminPlansTenantIdOverridesPatch(body);
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
| **tenantId** | `string` |  | [Defaults to `undefined`] |
| **featureOverrideRequest** | [FeatureOverrideRequest](FeatureOverrideRequest.md) |  | |
| **idempotencyKey** | `string` |  | [Optional] [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopeTenantPlanResponse**](SuccessEnvelopeTenantPlanResponse.md)

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

