
# UsageTimeseriesResponse


## Properties

Name | Type
------------ | -------------
`metric` | string
`granularity` | string
`points` | Array&lt;{ [key: string]: any; }&gt;

## Example

```typescript
import type { UsageTimeseriesResponse } from 'nexusrag-sdk'

// TODO: Update the object below with actual values
const example = {
  "metric": null,
  "granularity": null,
  "points": null,
} satisfies UsageTimeseriesResponse

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as UsageTimeseriesResponse
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


