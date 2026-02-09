
# AuditEventResponse


## Properties

Name | Type
------------ | -------------
`id` | number
`occurredAt` | string
`tenantId` | string
`actorType` | string
`actorId` | string
`actorRole` | string
`eventType` | string
`outcome` | string
`resourceType` | string
`resourceId` | string
`requestId` | string
`ipAddress` | string
`userAgent` | string
`metadataJson` | { [key: string]: any; }
`errorCode` | string
`createdAt` | string

## Example

```typescript
import type { AuditEventResponse } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "id": null,
  "occurredAt": null,
  "tenantId": null,
  "actorType": null,
  "actorId": null,
  "actorRole": null,
  "eventType": null,
  "outcome": null,
  "resourceType": null,
  "resourceId": null,
  "requestId": null,
  "ipAddress": null,
  "userAgent": null,
  "metadataJson": null,
  "errorCode": null,
  "createdAt": null,
} satisfies AuditEventResponse

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as AuditEventResponse
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


