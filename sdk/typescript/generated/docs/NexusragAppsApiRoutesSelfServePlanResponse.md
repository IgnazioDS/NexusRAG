
# NexusragAppsApiRoutesSelfServePlanResponse


## Properties

Name | Type
------------ | -------------
`tenantId` | string
`planId` | string
`planName` | string
`entitlements` | Array&lt;{ [key: string]: any; }&gt;
`quota` | { [key: string]: any; }

## Example

```typescript
import type { NexusragAppsApiRoutesSelfServePlanResponse } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "tenantId": null,
  "planId": null,
  "planName": null,
  "entitlements": null,
  "quota": null,
} satisfies NexusragAppsApiRoutesSelfServePlanResponse

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as NexusragAppsApiRoutesSelfServePlanResponse
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


