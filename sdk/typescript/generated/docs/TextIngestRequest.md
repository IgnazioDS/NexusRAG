
# TextIngestRequest


## Properties

Name | Type
------------ | -------------
`corpusId` | string
`text` | string
`documentId` | string
`filename` | string
`metadataJson` | { [key: string]: any; }
`chunkSizeChars` | number
`chunkOverlapChars` | number
`overwrite` | boolean

## Example

```typescript
import type { TextIngestRequest } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "corpusId": null,
  "text": null,
  "documentId": null,
  "filename": null,
  "metadataJson": null,
  "chunkSizeChars": null,
  "chunkOverlapChars": null,
  "overwrite": null,
} satisfies TextIngestRequest

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as TextIngestRequest
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


