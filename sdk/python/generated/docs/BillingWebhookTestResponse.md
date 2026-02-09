# BillingWebhookTestResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**sent** | **bool** |  | 
**status_code** | **int** |  | 
**delivery_id** | **str** |  | 
**message** | **str** |  | 

## Example

```python
from nexusrag_sdk.models.billing_webhook_test_response import BillingWebhookTestResponse

# TODO update the JSON string below
json = "{}"
# create an instance of BillingWebhookTestResponse from a JSON string
billing_webhook_test_response_instance = BillingWebhookTestResponse.from_json(json)
# print the JSON string representation of the object
print(BillingWebhookTestResponse.to_json())

# convert the object into a dict
billing_webhook_test_response_dict = billing_webhook_test_response_instance.to_dict()
# create an instance of BillingWebhookTestResponse from a dict
billing_webhook_test_response_from_dict = BillingWebhookTestResponse.from_dict(billing_webhook_test_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


