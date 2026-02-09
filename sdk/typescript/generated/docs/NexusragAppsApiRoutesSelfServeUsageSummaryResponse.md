
# NexusragAppsApiRoutesSelfServeUsageSummaryResponse


## Properties

Name | Type
------------ | -------------
`windowDays` | number
`requests` | { [key: string]: any; }
`quota` | { [key: string]: any; }
`rateLimitHits` | { [key: string]: any; }
`ingestion` | { [key: string]: any; }

## Example

```typescript
import type { NexusragAppsApiRoutesSelfServeUsageSummaryResponse } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "windowDays": null,
  "requests": null,
  "quota": null,
  "rateLimitHits": null,
  "ingestion": null,
} satisfies NexusragAppsApiRoutesSelfServeUsageSummaryResponse

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as NexusragAppsApiRoutesSelfServeUsageSummaryResponse
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


