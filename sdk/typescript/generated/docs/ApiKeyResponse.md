
# ApiKeyResponse


## Properties

Name | Type
------------ | -------------
`keyId` | string
`keyPrefix` | string
`name` | string
`role` | string
`createdAt` | string
`lastUsedAt` | string
`revokedAt` | string
`isActive` | boolean

## Example

```typescript
import type { ApiKeyResponse } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "keyId": null,
  "keyPrefix": null,
  "name": null,
  "role": null,
  "createdAt": null,
  "lastUsedAt": null,
  "revokedAt": null,
  "isActive": null,
} satisfies ApiKeyResponse

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as ApiKeyResponse
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


