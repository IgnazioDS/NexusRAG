
# PlanUpgradeRequestPayload


## Properties

Name | Type
------------ | -------------
`targetPlan` | string
`reason` | string

## Example

```typescript
import type { PlanUpgradeRequestPayload } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "targetPlan": null,
  "reason": null,
} satisfies PlanUpgradeRequestPayload

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as PlanUpgradeRequestPayload
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


