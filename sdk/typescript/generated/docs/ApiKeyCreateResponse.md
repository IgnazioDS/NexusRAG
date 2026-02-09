
# ApiKeyCreateResponse


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
`apiKey` | string

## Example

```typescript
import type { ApiKeyCreateResponse } from 'nexusrag-sdk'

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
  "apiKey": null,
} satisfies ApiKeyCreateResponse

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as ApiKeyCreateResponse
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


