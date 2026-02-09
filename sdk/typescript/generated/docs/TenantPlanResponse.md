
# TenantPlanResponse


## Properties

Name | Type
------------ | -------------
`tenantId` | string
`planId` | string
`planName` | string
`effectiveFrom` | string
`effectiveTo` | string
`isActive` | boolean
`entitlements` | [Array&lt;PlanFeatureResponse&gt;](PlanFeatureResponse.md)

## Example

```typescript
import type { TenantPlanResponse } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "tenantId": null,
  "planId": null,
  "planName": null,
  "effectiveFrom": null,
  "effectiveTo": null,
  "isActive": null,
  "entitlements": null,
} satisfies TenantPlanResponse

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as TenantPlanResponse
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


