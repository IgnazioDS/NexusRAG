
# AuditEventsPage


## Properties

Name | Type
------------ | -------------
`items` | [Array&lt;AuditEventResponse&gt;](AuditEventResponse.md)
`nextOffset` | number

## Example

```typescript
import type { AuditEventsPage } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "items": null,
  "nextOffset": null,
} satisfies AuditEventsPage

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as AuditEventsPage
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


