# PlanAssignmentRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**plan_id** | **str** |  | 

## Example

```python
from nexusrag_sdk.models.plan_assignment_request import PlanAssignmentRequest

# TODO update the JSON string below
json = "{}"
# create an instance of PlanAssignmentRequest from a JSON string
plan_assignment_request_instance = PlanAssignmentRequest.from_json(json)
# print the JSON string representation of the object
print(PlanAssignmentRequest.to_json())

# convert the object into a dict
plan_assignment_request_dict = plan_assignment_request_instance.to_dict()
# create an instance of PlanAssignmentRequest from a dict
plan_assignment_request_from_dict = PlanAssignmentRequest.from_dict(plan_assignment_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


