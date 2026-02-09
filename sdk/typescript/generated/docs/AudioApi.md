# AudioApi

All URIs are relative to *http://localhost:8000*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**getAudioV1AudioAudioIdMp3Get**](AudioApi.md#getaudiov1audioaudioidmp3get) | **GET** /v1/audio/{audio_id}.mp3 | Get Audio |



## getAudioV1AudioAudioIdMp3Get

> any getAudioV1AudioAudioIdMp3Get(audioId)

Get Audio

### Example

```ts
import {
  Configuration,
  AudioApi,
} from 'nexusrag-sdk';
import type { GetAudioV1AudioAudioIdMp3GetRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const api = new AudioApi();

  const body = {
    // string
    audioId: audioId_example,
  } satisfies GetAudioV1AudioAudioIdMp3GetRequest;

  try {
    const data = await api.getAudioV1AudioAudioIdMp3Get(body);
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
| **audioId** | `string` |  | [Defaults to `undefined`] |

### Return type

**any**

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

