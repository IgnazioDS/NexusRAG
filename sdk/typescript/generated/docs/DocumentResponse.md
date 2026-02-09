
# DocumentResponse


## Properties

Name | Type
------------ | -------------
`id` | string
`tenantId` | string
`corpusId` | string
`filename` | string
`contentType` | string
`source` | string
`ingestSource` | string
`status` | string
`failureReason` | string
`createdAt` | string
`updatedAt` | string
`queuedAt` | string
`processingStartedAt` | string
`completedAt` | string
`lastReindexedAt` | string
`lastJobId` | string
`numChunks` | number

## Example

```typescript
import type { DocumentResponse } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "id": null,
  "tenantId": null,
  "corpusId": null,
  "filename": null,
  "contentType": null,
  "source": null,
  "ingestSource": null,
  "status": null,
  "failureReason": null,
  "createdAt": null,
  "updatedAt": null,
  "queuedAt": null,
  "processingStartedAt": null,
  "completedAt": null,
  "lastReindexedAt": null,
  "lastJobId": null,
  "numChunks": null,
} satisfies DocumentResponse

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as DocumentResponse
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


