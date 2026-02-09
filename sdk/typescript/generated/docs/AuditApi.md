# AuditApi

All URIs are relative to *http://localhost:8000*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**getAuditEventV1AuditEventsEventIdGet**](AuditApi.md#getauditeventv1auditeventseventidget) | **GET** /v1/audit/events/{event_id} | Get Audit Event |
| [**listAuditEventsV1AuditEventsGet**](AuditApi.md#listauditeventsv1auditeventsget) | **GET** /v1/audit/events | List Audit Events |



## getAuditEventV1AuditEventsEventIdGet

> SuccessEnvelopeAuditEventResponse getAuditEventV1AuditEventsEventIdGet(eventId)

Get Audit Event

### Example

```ts
import {
  Configuration,
  AuditApi,
} from 'nexusrag-sdk';
import type { GetAuditEventV1AuditEventsEventIdGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new AuditApi(config);

  const body = {
    // number
    eventId: 56,
  } satisfies GetAuditEventV1AuditEventsEventIdGetRequest;

  try {
    const data = await api.getAuditEventV1AuditEventsEventIdGet(body);
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
| **eventId** | `number` |  | [Defaults to `undefined`] |

### Return type

[**SuccessEnvelopeAuditEventResponse**](SuccessEnvelopeAuditEventResponse.md)

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


## listAuditEventsV1AuditEventsGet

> SuccessEnvelopeAuditEventsPage listAuditEventsV1AuditEventsGet(tenantId, eventType, outcome, resourceType, resourceId, from, to, offset, limit)

List Audit Events

### Example

```ts
import {
  Configuration,
  AuditApi,
} from 'nexusrag-sdk';
import type { ListAuditEventsV1AuditEventsGetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new AuditApi(config);

  const body = {
    // string (optional)
    tenantId: tenantId_example,
    // string (optional)
    eventType: eventType_example,
    // string (optional)
    outcome: outcome_example,
    // string (optional)
    resourceType: resourceType_example,
    // string (optional)
    resourceId: resourceId_example,
    // Date (optional)
    from: 2013-10-20T19:20:30+01:00,
    // Date (optional)
    to: 2013-10-20T19:20:30+01:00,
    // number (optional)
    offset: 56,
    // number (optional)
    limit: 56,
  } satisfies ListAuditEventsV1AuditEventsGetRequest;

  try {
    const data = await api.listAuditEventsV1AuditEventsGet(body);
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
| **tenantId** | `string` |  | [Optional] [Defaults to `undefined`] |
| **eventType** | `string` |  | [Optional] [Defaults to `undefined`] |
| **outcome** | `string` |  | [Optional] [Defaults to `undefined`] |
| **resourceType** | `string` |  | [Optional] [Defaults to `undefined`] |
| **resourceId** | `string` |  | [Optional] [Defaults to `undefined`] |
| **from** | `Date` |  | [Optional] [Defaults to `undefined`] |
| **to** | `Date` |  | [Optional] [Defaults to `undefined`] |
| **offset** | `number` |  | [Optional] [Defaults to `0`] |
| **limit** | `number` |  | [Optional] [Defaults to `50`] |

### Return type

[**SuccessEnvelopeAuditEventsPage**](SuccessEnvelopeAuditEventsPage.md)

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

