
# FeatureOverrideRequest


## Properties

Name | Type
------------ | -------------
`featureKey` | string
`enabled` | boolean
`configJson` | { [key: string]: any; }

## Example

```typescript
import type { FeatureOverrideRequest } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "featureKey": null,
  "enabled": null,
  "configJson": null,
} satisfies FeatureOverrideRequest

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as FeatureOverrideRequest
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


