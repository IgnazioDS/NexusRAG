# nexusrag-sdk@v1

A TypeScript SDK client for the localhost API.

## Usage

First, install the SDK from npm.

```bash
npm install nexusrag-sdk --save
```

Next, try it out.


```ts
import {
  Configuration,
  AdminApi,
} from 'nexusrag-sdk';
import type { AssignTenantPlanV1AdminPlansTenantIdPatchRequest } from 'nexusrag-sdk';

async function example() {
  console.log("🚀 Testing nexusrag-sdk SDK...");
  const config = new Configuration({ 
    // Configure HTTP bearer authorization: BearerAuth
    accessToken: "YOUR BEARER TOKEN",
  });
  const api = new AdminApi(config);

  const body = {
    // string
    tenantId: tenantId_example,
    // PlanAssignmentRequest
    planAssignmentRequest: ...,
    // string (optional)
    idempotencyKey: idempotencyKey_example,
  } satisfies AssignTenantPlanV1AdminPlansTenantIdPatchRequest;

  try {
    const data = await api.assignTenantPlanV1AdminPlansTenantIdPatch(body);
    console.log(data);
  } catch (error) {
    console.error(error);
  }
}

// Run the test
example().catch(console.error);
```


## Documentation

### API Endpoints

All URIs are relative to *http://localhost:8000*

| Class | Method | HTTP request | Description
| ----- | ------ | ------------ | -------------
*AdminApi* | [**assignTenantPlanV1AdminPlansTenantIdPatch**](docs/AdminApi.md#assigntenantplanv1adminplanstenantidpatch) | **PATCH** /v1/admin/plans/{tenant_id} | Assign Tenant Plan
*AdminApi* | [**getQuotaLimitsV1AdminQuotasTenantIdGet**](docs/AdminApi.md#getquotalimitsv1adminquotastenantidget) | **GET** /v1/admin/quotas/{tenant_id} | Get Quota Limits
*AdminApi* | [**getTenantPlanV1AdminPlansTenantIdGet**](docs/AdminApi.md#gettenantplanv1adminplanstenantidget) | **GET** /v1/admin/plans/{tenant_id} | Get Tenant Plan
*AdminApi* | [**getUsageSummaryV1AdminUsageTenantIdGet**](docs/AdminApi.md#getusagesummaryv1adminusagetenantidget) | **GET** /v1/admin/usage/{tenant_id} | Get Usage Summary
*AdminApi* | [**listPlansV1AdminPlansGet**](docs/AdminApi.md#listplansv1adminplansget) | **GET** /v1/admin/plans | List Plans
*AdminApi* | [**patchQuotaLimitsV1AdminQuotasTenantIdPatch**](docs/AdminApi.md#patchquotalimitsv1adminquotastenantidpatch) | **PATCH** /v1/admin/quotas/{tenant_id} | Patch Quota Limits
*AdminApi* | [**patchTenantOverridesV1AdminPlansTenantIdOverridesPatch**](docs/AdminApi.md#patchtenantoverridesv1adminplanstenantidoverridespatch) | **PATCH** /v1/admin/plans/{tenant_id}/overrides | Patch Tenant Overrides
*AudioApi* | [**getAudioV1AudioAudioIdMp3Get**](docs/AudioApi.md#getaudiov1audioaudioidmp3get) | **GET** /v1/audio/{audio_id}.mp3 | Get Audio
*AuditApi* | [**getAuditEventV1AuditEventsEventIdGet**](docs/AuditApi.md#getauditeventv1auditeventseventidget) | **GET** /v1/audit/events/{event_id} | Get Audit Event
*AuditApi* | [**listAuditEventsV1AuditEventsGet**](docs/AuditApi.md#listauditeventsv1auditeventsget) | **GET** /v1/audit/events | List Audit Events
*CorporaApi* | [**getCorpusV1CorporaCorpusIdGet**](docs/CorporaApi.md#getcorpusv1corporacorpusidget) | **GET** /v1/corpora/{corpus_id} | Get Corpus
*CorporaApi* | [**listCorporaV1CorporaGet**](docs/CorporaApi.md#listcorporav1corporaget) | **GET** /v1/corpora | List Corpora
*CorporaApi* | [**patchCorpusV1CorporaCorpusIdPatch**](docs/CorporaApi.md#patchcorpusv1corporacorpusidpatch) | **PATCH** /v1/corpora/{corpus_id} | Patch Corpus
*DocumentsApi* | [**deleteDocumentV1DocumentsDocumentIdDelete**](docs/DocumentsApi.md#deletedocumentv1documentsdocumentiddelete) | **DELETE** /v1/documents/{document_id} | Delete Document
*DocumentsApi* | [**getDocumentV1DocumentsDocumentIdGet**](docs/DocumentsApi.md#getdocumentv1documentsdocumentidget) | **GET** /v1/documents/{document_id} | Get Document
*DocumentsApi* | [**ingestTextDocumentV1DocumentsTextPost**](docs/DocumentsApi.md#ingesttextdocumentv1documentstextpost) | **POST** /v1/documents/text | Ingest Text Document
*DocumentsApi* | [**listDocumentsV1DocumentsGet**](docs/DocumentsApi.md#listdocumentsv1documentsget) | **GET** /v1/documents | List Documents
*DocumentsApi* | [**reindexDocumentV1DocumentsDocumentIdReindexPost**](docs/DocumentsApi.md#reindexdocumentv1documentsdocumentidreindexpost) | **POST** /v1/documents/{document_id}/reindex | Reindex Document
*DocumentsApi* | [**uploadDocumentV1DocumentsPost**](docs/DocumentsApi.md#uploaddocumentv1documentspost) | **POST** /v1/documents | Upload Document
*HealthApi* | [**healthV1HealthGet**](docs/HealthApi.md#healthv1healthget) | **GET** /v1/health | Health
*OpsApi* | [**opsHealthV1OpsHealthGet**](docs/OpsApi.md#opshealthv1opshealthget) | **GET** /v1/ops/health | Ops Health
*OpsApi* | [**opsIngestionV1OpsIngestionGet**](docs/OpsApi.md#opsingestionv1opsingestionget) | **GET** /v1/ops/ingestion | Ops Ingestion
*OpsApi* | [**opsMetricsV1OpsMetricsGet**](docs/OpsApi.md#opsmetricsv1opsmetricsget) | **GET** /v1/ops/metrics | Ops Metrics
*RunApi* | [**runV1RunPost**](docs/RunApi.md#runv1runpost) | **POST** /v1/run | Run
*SelfServeApi* | [**billingWebhookTestV1SelfServeBillingWebhookTestPost**](docs/SelfServeApi.md#billingwebhooktestv1selfservebillingwebhooktestpost) | **POST** /v1/self-serve/billing/webhook-test | Billing Webhook Test
*SelfServeApi* | [**createApiKeyV1SelfServeApiKeysPost**](docs/SelfServeApi.md#createapikeyv1selfserveapikeyspost) | **POST** /v1/self-serve/api-keys | Create Api Key
*SelfServeApi* | [**getSelfServePlanV1SelfServePlanGet**](docs/SelfServeApi.md#getselfserveplanv1selfserveplanget) | **GET** /v1/self-serve/plan | Get Self Serve Plan
*SelfServeApi* | [**listApiKeysV1SelfServeApiKeysGet**](docs/SelfServeApi.md#listapikeysv1selfserveapikeysget) | **GET** /v1/self-serve/api-keys | List Api Keys
*SelfServeApi* | [**revokeApiKeyV1SelfServeApiKeysKeyIdRevokePost**](docs/SelfServeApi.md#revokeapikeyv1selfserveapikeyskeyidrevokepost) | **POST** /v1/self-serve/api-keys/{key_id}/revoke | Revoke Api Key
*SelfServeApi* | [**upgradePlanRequestV1SelfServePlanUpgradeRequestPost**](docs/SelfServeApi.md#upgradeplanrequestv1selfserveplanupgraderequestpost) | **POST** /v1/self-serve/plan/upgrade-request | Upgrade Plan Request
*SelfServeApi* | [**usageSummaryV1SelfServeUsageSummaryGet**](docs/SelfServeApi.md#usagesummaryv1selfserveusagesummaryget) | **GET** /v1/self-serve/usage/summary | Usage Summary
*SelfServeApi* | [**usageTimeseriesV1SelfServeUsageTimeseriesGet**](docs/SelfServeApi.md#usagetimeseriesv1selfserveusagetimeseriesget) | **GET** /v1/self-serve/usage/timeseries | Usage Timeseries


### Models

- [ApiKeyCreateRequest](docs/ApiKeyCreateRequest.md)
- [ApiKeyCreateResponse](docs/ApiKeyCreateResponse.md)
- [ApiKeyListResponse](docs/ApiKeyListResponse.md)
- [ApiKeyResponse](docs/ApiKeyResponse.md)
- [AuditEventResponse](docs/AuditEventResponse.md)
- [AuditEventsPage](docs/AuditEventsPage.md)
- [BillingWebhookTestResponse](docs/BillingWebhookTestResponse.md)
- [CorpusPatchRequest](docs/CorpusPatchRequest.md)
- [CorpusResponse](docs/CorpusResponse.md)
- [DocumentAccepted](docs/DocumentAccepted.md)
- [DocumentResponse](docs/DocumentResponse.md)
- [ErrorDetail](docs/ErrorDetail.md)
- [ErrorEnvelope](docs/ErrorEnvelope.md)
- [FeatureOverrideRequest](docs/FeatureOverrideRequest.md)
- [HealthResponse](docs/HealthResponse.md)
- [NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse1](docs/NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse1.md)
- [NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse2](docs/NexusragAppsApiResponseSuccessEnvelopeUsageSummaryResponse2.md)
- [NexusragAppsApiRoutesAdminPlanResponse](docs/NexusragAppsApiRoutesAdminPlanResponse.md)
- [NexusragAppsApiRoutesAdminUsageSummaryResponse](docs/NexusragAppsApiRoutesAdminUsageSummaryResponse.md)
- [NexusragAppsApiRoutesSelfServePlanResponse](docs/NexusragAppsApiRoutesSelfServePlanResponse.md)
- [NexusragAppsApiRoutesSelfServeUsageSummaryResponse](docs/NexusragAppsApiRoutesSelfServeUsageSummaryResponse.md)
- [PlanAssignmentRequest](docs/PlanAssignmentRequest.md)
- [PlanFeatureResponse](docs/PlanFeatureResponse.md)
- [PlanLimitPatchRequest](docs/PlanLimitPatchRequest.md)
- [PlanLimitResponse](docs/PlanLimitResponse.md)
- [PlanUpgradeRequestPayload](docs/PlanUpgradeRequestPayload.md)
- [PlanUpgradeResponse](docs/PlanUpgradeResponse.md)
- [ReindexRequest](docs/ReindexRequest.md)
- [ResponseMeta](docs/ResponseMeta.md)
- [RunRequest](docs/RunRequest.md)
- [SuccessEnvelopeApiKeyCreateResponse](docs/SuccessEnvelopeApiKeyCreateResponse.md)
- [SuccessEnvelopeApiKeyListResponse](docs/SuccessEnvelopeApiKeyListResponse.md)
- [SuccessEnvelopeApiKeyResponse](docs/SuccessEnvelopeApiKeyResponse.md)
- [SuccessEnvelopeAuditEventResponse](docs/SuccessEnvelopeAuditEventResponse.md)
- [SuccessEnvelopeAuditEventsPage](docs/SuccessEnvelopeAuditEventsPage.md)
- [SuccessEnvelopeBillingWebhookTestResponse](docs/SuccessEnvelopeBillingWebhookTestResponse.md)
- [SuccessEnvelopeCorpusResponse](docs/SuccessEnvelopeCorpusResponse.md)
- [SuccessEnvelopeDictStrAny](docs/SuccessEnvelopeDictStrAny.md)
- [SuccessEnvelopeDocumentAccepted](docs/SuccessEnvelopeDocumentAccepted.md)
- [SuccessEnvelopeDocumentResponse](docs/SuccessEnvelopeDocumentResponse.md)
- [SuccessEnvelopeHealthResponse](docs/SuccessEnvelopeHealthResponse.md)
- [SuccessEnvelopeListCorpusResponse](docs/SuccessEnvelopeListCorpusResponse.md)
- [SuccessEnvelopeListDocumentResponse](docs/SuccessEnvelopeListDocumentResponse.md)
- [SuccessEnvelopeListPlanResponse](docs/SuccessEnvelopeListPlanResponse.md)
- [SuccessEnvelopePlanLimitResponse](docs/SuccessEnvelopePlanLimitResponse.md)
- [SuccessEnvelopePlanResponse](docs/SuccessEnvelopePlanResponse.md)
- [SuccessEnvelopePlanUpgradeResponse](docs/SuccessEnvelopePlanUpgradeResponse.md)
- [SuccessEnvelopeTenantPlanResponse](docs/SuccessEnvelopeTenantPlanResponse.md)
- [SuccessEnvelopeUsageTimeseriesResponse](docs/SuccessEnvelopeUsageTimeseriesResponse.md)
- [TenantPlanResponse](docs/TenantPlanResponse.md)
- [TextIngestRequest](docs/TextIngestRequest.md)
- [UsageTimeseriesResponse](docs/UsageTimeseriesResponse.md)

### Authorization


Authentication schemes defined for the API:
<a id="BearerAuth"></a>
#### BearerAuth


- **Type**: HTTP Bearer Token authentication

## About

This TypeScript SDK client supports the [Fetch API](https://fetch.spec.whatwg.org/)
and is automatically generated by the
[OpenAPI Generator](https://openapi-generator.tech) project:

- API version: `v1`
- Package version: `v1`
- Generator version: `7.20.0-SNAPSHOT`
- Build package: `org.openapitools.codegen.languages.TypeScriptFetchClientCodegen`

The generated npm module supports the following:

- Environments
  * Node.js
  * Webpack
  * Browserify
- Language levels
  * ES5 - you must have a Promises/A+ library installed
  * ES6
- Module systems
  * CommonJS
  * ES6 module system


## Development

### Building

To build the TypeScript source code, you need to have Node.js and npm installed.
After cloning the repository, navigate to the project directory and run:

```bash
npm install
npm run build
```

### Publishing

Once you've built the package, you can publish it to npm:

```bash
npm publish
```

## License

[]()
