
# RunRequest


## Properties

Name | Type
------------ | -------------
`sessionId` | string
`corpusId` | string
`message` | string
`topK` | number
`audio` | boolean

## Example

```typescript
import type { RunRequest } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "sessionId": null,
  "corpusId": null,
  "message": null,
  "topK": null,
  "audio": null,
} satisfies RunRequest

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as RunRequest
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


