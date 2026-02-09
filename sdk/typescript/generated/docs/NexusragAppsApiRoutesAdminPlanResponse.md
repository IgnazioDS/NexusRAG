
# NexusragAppsApiRoutesAdminPlanResponse


## Properties

Name | Type
------------ | -------------
`id` | string
`name` | string
`isActive` | boolean
`features` | [Array&lt;PlanFeatureResponse&gt;](PlanFeatureResponse.md)

## Example

```typescript
import type { NexusragAppsApiRoutesAdminPlanResponse } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "id": null,
  "name": null,
  "isActive": null,
  "features": null,
} satisfies NexusragAppsApiRoutesAdminPlanResponse

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as NexusragAppsApiRoutesAdminPlanResponse
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


