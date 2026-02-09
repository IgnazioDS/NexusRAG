
# PlanLimitPatchRequest


## Properties

Name | Type
------------ | -------------
`dailyRequestsLimit` | number
`monthlyRequestsLimit` | number
`dailyTokensLimit` | number
`monthlyTokensLimit` | number
`softCapRatio` | number
`hardCapEnabled` | boolean

## Example

```typescript
import type { PlanLimitPatchRequest } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "dailyRequestsLimit": null,
  "monthlyRequestsLimit": null,
  "dailyTokensLimit": null,
  "monthlyTokensLimit": null,
  "softCapRatio": null,
  "hardCapEnabled": null,
} satisfies PlanLimitPatchRequest

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as PlanLimitPatchRequest
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


