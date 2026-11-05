# Math tutor infrastructure

There are two entry points:

- Root `azd up` uses [azd/main.bicep](azd/main.bicep) to create a resource group,
  public Foundry account/project, model, developer model-invocation role, ACR,
  and project image-pull access. It then builds and deploys the hosted agent.
- GitHub Release calls Infrastructure automatically for dev, using
  [main.bicep](main.bicep) and [environment parameters](environments/).
  It reconciles the group, public Foundry account/project, model, and ACR
  before building. Test/prod use manual Infrastructure `plan`/`apply`.

The resource-group template creates the following with its default options:

- A modern Microsoft Foundry account (`AIServices`, S0), not a legacy AI hub.
- A Foundry project under that account.
- A Basic Azure Container Registry (ACR).
- An `AcrPull` assignment for the project's system-assigned managed identity,
  scoped to this registry.
- A managed-identity ACR project connection.
- Optionally, an explicitly versioned OpenAI model deployment (`deployModel`).

The account and project have system-assigned identities. Public endpoints are
enabled, but Foundry key authentication, ACR admin credentials, and anonymous
image pulls are disabled. The registry uses registry-level RBAC so `AcrPull`
applies; it is not configured for repository-level ABAC.

No Azure resources are created by adding or compiling these files. Deployment
will incur Azure charges, including ongoing ACR charges.

## Configure and validate

Install Azure CLI with Bicep support. Edit [main.bicepparam](main.bicepparam) to
choose your location and tags. `northcentralus` is an example, not a guarantee of
current hosted-agent capacity or model availability. Resource names default to
stable, resource-group-derived names; override the name parameters if needed.
ACR names must be globally unique, 5-50 lowercase letters/numbers. Foundry account
names/custom subdomains must also be globally unique.

Run from the repository root:

```powershell
az bicep build --file .\infra\main.bicep --stdout > $null
az bicep build-params --file .\infra\main.bicepparam --stdout > $null
```

These are local compilation checks, not Azure-side deployment validation.

For GitHub Actions, use [environment parameters](environments/) and the
[CI/CD bootstrap guide](../ci-cd.md#10-bootstrap-the-implemented-workflows).
The infrastructure workflow loads the selected parameter file, overrides its
location from the protected GitHub Environment, and preserves custom resource
names. Apply can create a missing group when authorized; plan requires an
existing group. Precreating groups allows narrowly scoped bootstrap roles.
The workflow enables model provisioning by default with `gpt-5-mini`,
`2025-08-07`, `GlobalStandard`, capacity 1; reviewed environment variables can
override this policy. Direct Bicep defaults still leave model creation off.

Release passes dev outputs to its build/deploy jobs automatically through the
`infrastructure-dev` artifact, rather than copying them into GitHub variables.
Configure test/prod variables from their separately approved infrastructure
outputs. Deployments grant model access to the returned hosted instance
identity before live smoke; the deployer needs constrained role-assignment
permission on that model account. GitHub identities/federation, protected
Environments, their bootstrap roles, and monitoring are not created here.

## Deploy when ready

### Azure Developer CLI: complete hosted-agent deployment

The root [azure.yaml](../azure.yaml) uses the subscription-scoped
[azd entry point](azd/main.bicep), which reuses the resource-group template.
It creates `rg-<environment>`, a public Foundry account/project, and a
`gpt-5-mini` model deployment pinned to `2025-08-07`, using `GlobalStandard`
with capacity 1. Confirm regional model availability and subscription quota
before deploying. GlobalStandard may process requests outside the resource's
region; use an appropriate supported SKU if data residency is required.

The [math-tutor service](../azure.yaml) uses remote ACR builds of the existing
Dockerfile, then deploys a hosted agent with Responses protocol 2.0.0, 1 CPU,
and 2 GiB memory. Local Docker is not required. Public network access does not
mean anonymous access: local/key authentication stays disabled. The developer
receives the `Cognitive Services OpenAI User` role on the account.

```powershell
az login
azd auth login
azd extension install azure.ai.agents
azd env new math-tutor-dev --no-prompt
azd env set AZURE_SUBSCRIPTION_ID '<subscription-id>'
azd env set AZURE_LOCATION northcentralus
azd env set AZURE_PRINCIPAL_ID (az ad signed-in-user show --query id -o tsv)
azd provision --preview --no-prompt
azd up --no-prompt
azd env get-values
```

The environment is saved under the ignored `.azure` directory. Model defaults
are parameters in the azd entry point; override them through
[main.parameters.json](azd/main.parameters.json) when choosing a different
model/version/SKU/capacity. Model use incurs charges; capacity 1 is a quota
allocation, not a spending limit.

Set `AZURE_OPENAI_ENDPOINT` and `AZURE_AI_MODEL_DEPLOYMENT_NAME` from the azd
outputs in your local environment to use this model. Provisioning does not
overwrite your existing `.env` or invoke the model. Re-running `azd up`
reconciles this same infrastructure and deploys a new hosted-agent version;
use a different environment name for independent resources.

Use `azd provision --no-prompt` for infrastructure only, or
`azd deploy math-tutor --no-prompt` for a code-only redeployment. The wrapper
exports ACR name, login server and resource ID, project endpoint (including
`FOUNDRY_PROJECT_ENDPOINT` for the extension), project ID, and tenant ID.
The hosted service receives its model configuration explicitly and disables
Swagger. `azd ai agent show --output json` reports the deployed version;
`azd ai agent invoke "What is 3 times 4?"` performs a billable end-to-end check.
The [postdeploy hook](../scripts/azd_runtime.py) grants the returned hosted-agent
instance identity `Cognitive Services OpenAI User` at the model account scope.
It checks for an existing assignment and fails rather than silently skipping
missing outputs or permissions. Role propagation can take several minutes.

The model deployment waits for project creation because concurrent writes to
the same Foundry account can fail with `RequestConflict`. If an unrelated
operation temporarily locks the account, wait for that operation to finish and
re-run `azd up --no-prompt` against the same environment.

### Existing resource-group deployment

The following commands create Azure resources; they have not been run as part
of generating these templates. Replace the subscription and resource-group
values and confirm the region first.

```powershell
az login
az account set --subscription '<subscription-id>'
$resourceGroup = 'rg-math-tutor-dev'
az group create --name $resourceGroup --location northcentralus

az deployment group validate --resource-group $resourceGroup --parameters .\infra\main.bicepparam
az deployment group what-if --resource-group $resourceGroup --parameters .\infra\main.bicepparam
az deployment group create --name math-tutor-infra --resource-group $resourceGroup --parameters .\infra\main.bicepparam

az deployment group show --name math-tutor-infra --resource-group $resourceGroup --query properties.outputs --output json
```

The deploying identity needs resource creation permissions plus
`Microsoft.Authorization/roleAssignments/write` at the resource group or an
inherited scope. Contributor alone cannot create the role assignment. The
subscription must have `Microsoft.CognitiveServices` and
`Microsoft.ContainerRegistry` registered.

## Provisioning versus agent deployment

`azd provision` and direct ARM/Bicep deployments are infrastructure only.
`azd up` additionally builds/pushes the image and deploys the hosted agent;
`azd deploy` reruns just the application deployment. These commands do not
configure GitHub identities or enable Standard Setup capability hosts and
backing stores. The azd entry point grants the configured developer user
model-invocation access; the resource-group template does so only when
`principalId` is supplied. In the resource-group template, model deployment
is off by default.
To enable it, supply `deployModel=true`, a nonempty `modelName` and
`modelVersion`, and a region-supported SKU/capacity. Model quota and availability
must be checked in the chosen subscription. Automatic model upgrades are
disabled so test/prod model changes remain deliberate.

For the direct Bicep/GitHub path, complete these steps after provisioning:

1. Deploy or select a model. The output `AZURE_OPENAI_ENDPOINT` is the new
   account's model resource endpoint, **not** the project endpoint. Configure
   `AZURE_AI_MODEL_DEPLOYMENT_NAME` after creating the model deployment. The
   templates do not change your existing local model configuration.
2. Authorize the deployment identity to assign the model-user role on that
   account. The shared deployment helper grants it to the actual hosted
   runtime identity before smoke. For a custom deployment outside these
   workflows, grant runtime model access explicitly. Project image-pull
   permission does not imply runtime model access. Developers also need
   appropriate project/model roles to use the resources.
3. Give your image publishing/building identity appropriate ACR permissions.
   The project's `AcrPull` role cannot push images or submit ACR Tasks builds.
4. Build and push the repository's [Dockerfile](../dockerfile) as `linux/amd64`.
   ACR Tasks can build remotely if local Docker is unavailable.
5. Use the release workflow to register the image with Responses protocol
   `2.0.0` and container port 8088. Provisioning is automatic when the Foundry
   version is created; the pipeline waits for it to become active, runs live
   numeric smoke tests, and selects the tested version for the endpoint.

The outputs include the project endpoint, account and project IDs, project
principal ID, model resource endpoint, and registry login server. They contain
no keys or credentials.

`deployContainerRegistry` defaults to `true` for both deployment paths.
Setting it to false in a custom infrastructure-only deployment makes
registry-related outputs empty; container deployment then requires an existing
registry and project connection. The optional `principalId` parameter grants model
invocation to a developer user; it does not grant a future hosted-agent identity
model access.

## References

- [Foundry hosted-agent deployment](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent)
- [Foundry account Bicep reference](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2025-06-01/accounts)
- [Foundry project Bicep reference](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2025-06-01/accounts/projects)
