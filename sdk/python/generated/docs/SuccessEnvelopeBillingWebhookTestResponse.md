# SuccessEnvelopeBillingWebhookTestResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**BillingWebhookTestResponse**](BillingWebhookTestResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_billing_webhook_test_response import SuccessEnvelopeBillingWebhookTestResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeBillingWebhookTestResponse from a JSON string
success_envelope_billing_webhook_test_response_instance = SuccessEnvelopeBillingWebhookTestResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeBillingWebhookTestResponse.to_json())

# convert the object into a dict
success_envelope_billing_webhook_test_response_dict = success_envelope_billing_webhook_test_response_instance.to_dict()
# create an instance of SuccessEnvelopeBillingWebhookTestResponse from a dict
success_envelope_billing_webhook_test_response_from_dict = SuccessEnvelopeBillingWebhookTestResponse.from_dict(success_envelope_billing_webhook_test_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


