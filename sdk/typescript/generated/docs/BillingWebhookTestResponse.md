
# BillingWebhookTestResponse


## Properties

Name | Type
------------ | -------------
`sent` | boolean
`statusCode` | number
`deliveryId` | string
`message` | string

## Example

```typescript
import type { BillingWebhookTestResponse } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "sent": null,
  "statusCode": null,
  "deliveryId": null,
  "message": null,
} satisfies BillingWebhookTestResponse

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as BillingWebhookTestResponse
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


