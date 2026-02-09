# SuccessEnvelopeTenantPlanResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**TenantPlanResponse**](TenantPlanResponse.md) |  | 
**meta** | [**ResponseMeta**](ResponseMeta.md) |  | 

## Example

```python
from nexusrag_sdk.models.success_envelope_tenant_plan_response import SuccessEnvelopeTenantPlanResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SuccessEnvelopeTenantPlanResponse from a JSON string
success_envelope_tenant_plan_response_instance = SuccessEnvelopeTenantPlanResponse.from_json(json)
# print the JSON string representation of the object
print(SuccessEnvelopeTenantPlanResponse.to_json())

# convert the object into a dict
success_envelope_tenant_plan_response_dict = success_envelope_tenant_plan_response_instance.to_dict()
# create an instance of SuccessEnvelopeTenantPlanResponse from a dict
success_envelope_tenant_plan_response_from_dict = SuccessEnvelopeTenantPlanResponse.from_dict(success_envelope_tenant_plan_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


