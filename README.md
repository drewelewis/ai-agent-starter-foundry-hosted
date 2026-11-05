# Math Tutor Agent

A math tutor built with Microsoft Agent Framework, Azure OpenAI, and the
Microsoft Foundry Responses hosting SDK.
Local calculation tools provide reproducible answers; the agent explains formulas
and helps students work through problems. No database is required.

Start with [Getting started](#getting-started) for local setup, complete hosted
agent deployment with `azd up`, and your first conversation. For new features and
cloud releases, follow the [local -> dev -> test -> prod workflow](ci-cd.md#6-implement-a-feature-local---dev---test---prod).

**Two deployment paths:** `azd up` provisions developer infrastructure, builds
the container in ACR, and deploys the hosted agent. GitHub Actions provides the
protected dev -> test -> prod release path with immutable-image promotion.
On main, Release reconciles dev infrastructure and its model before building,
then grants the hosted identity model access and runs live smoke tests.
Do not let both paths independently deploy the same agent or manage the same
endpoint.

## Capabilities

| Topic | Operations |
|---|---|
| Arithmetic | `add`, `subtract`, `multiply`, `divide`, `power`, `modulo`, `evaluate_expression` |
| Plane geometry | `rectangle_area`, `rectangle_perimeter`, `triangle_area`, `triangle_perimeter`, `circle_area`, `circle_circumference` |
| Solid geometry | `cuboid_volume`, `cuboid_surface_area`, `cylinder_volume`, `cylinder_surface_area`, `sphere_volume`, `sphere_surface_area` |
| Right triangles and coordinates | `pythagorean_hypotenuse`, `coordinate_distance` |
| Algebra | `solve_linear_equation`, `solve_quadratic_equation` |
| Calculus | `differentiate_polynomial` |

Squares and cubes use the rectangle and cuboid tools with equal dimensions.
Geometry dimensions must be finite and strictly positive; coordinates can be
negative or zero. Triangle sides must satisfy the strict triangle inequality.
Use consistent units: results use units, square units, or cubic units.
No automatic unit conversion is performed. Unrepresentable geometry/algebra
results produce explicit errors rather than infinity.

Linear equations use `a*x + b = 0`. Quadratics use `a*x^2 + b*x + c = 0`.
The solvers handle zero coefficients, repeated roots, no solution, infinitely many
solutions, and no real roots. Quadratics with `a = 0` reduce to linear equations.
Only real solutions are supported; calculations use floating-point precision.

Polynomial derivatives use the power rule for a single variable, `x`, with
finite real coefficients and nonnegative integer powers. The tool accepts
coefficients in descending powers, including zeros for missing terms:
`3*x^2 + 1` is `[3, 0, 1]` and its derivative is `6*x`. Constants differentiate
to zero. Natural-language expressions are normalized by the tutor; the tool
does not parse or execute expression strings. General functions, negative or
fractional powers, integrals, and limits are not supported by this tool.
Invalid inputs and results outside the finite numeric range raise explicit errors.

## Getting started

### 1. Prerequisites

- Python 3.11, matching the Docker image.
- Azure CLI (`az`), Azure Developer CLI (`azd` >= 1.37.2), and its
  `azure.ai.agents` extension (>= 1.0.0-beta.20) for Azure deployment.
- An Azure subscription with a supported model/region and available quota.
- Permission to create a resource group, Foundry resources, and ACR; submit
  remote ACR builds; deploy agents; and assign developer/runtime roles.
  Contributor alone cannot assign roles.
- Docker is optional: `azd` uses remote ACR builds by default. Git and GitHub CLI (`gh`)
  are needed for the release examples in the [CI/CD guide](ci-cd.md).

Run commands from the repository root.

### 2. Create the Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pip check
if (-not (Test-Path .env)) { Copy-Item env.sample .env }
```

Alternatively, in **Command Prompt**, use the existing batch helpers:

```bat
_env_create.bat
_env_activate.bat
python -m pip install -r requirements-dev.txt
python -m pip check
if not exist .env copy env.sample .env
```

The [_install.bat](_install.bat) helper installs runtime requirements only;
use `requirements-dev.txt` for tests and debugging. Do not copy over an existing
`.env` containing your configuration.

### 3. Deploy public Foundry, ACR, and the hosted agent with azd

For local-only development with an existing model and invocation permissions,
skip deployment and go to [Configure the model](#4-configure-the-model).

[azure.yaml](azure.yaml) uses [infra/azd/main.bicep](infra/azd/main.bicep).
The following example creates an isolated developer environment named
`math-tutor-local`. Choose a region after checking model availability and quota;
`northcentralus` is an example, not a capacity guarantee.

```powershell
az login
az account set --subscription '<subscription-id>'
azd auth login
azd extension install azure.ai.agents
azd env new math-tutor-local --no-prompt
azd env set AZURE_SUBSCRIPTION_ID '<subscription-id>'
azd env set AZURE_LOCATION northcentralus
azd env set AZURE_PRINCIPAL_ID (az ad signed-in-user show --query id -o tsv)
azd provision --preview --no-prompt
# Review the preview before creating resources:
azd up --no-prompt
azd env get-values
```

If an azd environment already exists locally, use `azd env select <name>`
instead of `azd env new`. For example, select `math-tutor-dev` to reuse the
environment provisioned earlier in this workspace. Check its subscription and
region before provisioning again.

**What `azd up` creates with the current defaults:**

| Resource | Configuration |
|---|---|
| Resource group | `rg-<azd-environment>`, tagged with `azd-env-name` |
| Foundry account | Generated `foundry-...` name, AIServices S0, system-assigned identity |
| Foundry project | `math-tutor`, with its own system-assigned identity |
| Model deployment | Deployment name and model `gpt-5-mini`, version `2025-08-07` |
| Model SKU/capacity | `GlobalStandard`, capacity 100 (100 RPM / 100,000 TPM for this model), automatic model upgrades disabled |
| Developer permission | `Cognitive Services OpenAI User` scoped to the new account |
| Container registry | Basic ACR, admin/anonymous access disabled |
| Image-pull access | Project managed identity `AcrPull` assignment and registry connection |
| Container image | Remote ACR build of [dockerfile](dockerfile), targeting `linux/amd64` |
| Hosted agent | `math-tutor`, Responses 2.0.0, port 8088, 1 CPU / 2 GiB memory |

`azd` passes the provisioned model endpoint/deployment into the container.
Swagger and message-content telemetry remain disabled in the hosted runtime.

Public network access is enabled, but Entra authentication is required and
local/key authentication is disabled. GlobalStandard can process requests outside
the resource region. Model usage incurs Azure charges; capacity 100 is not a
spending cap. Review the model/SKU/version parameters before adopting this
configuration for a different workload.

Capacity is a model-specific quota allocation, not separately configurable RPM
and TPM limits. The selected GPT-5-mini GlobalStandard deployment uses 1 RPM and
1,000 TPM per unit. Confirm available quota before deploying each environment;
the default allocates 100 units per model deployment. Other models/SKUs can use
different ratios.

ACR storage/builds and hosted compute also incur charges. The deployer needs
permission to assign the runtime identity's model access; project image-pull
access alone does not grant model invocation. The postdeploy hook grants
`Cognitive Services OpenAI User` on the model account to the actual hosted
identity returned by Foundry. It is idempotent and fails the command explicitly
if required outputs or role-assignment permissions are missing. Allow several
minutes for new Azure role assignments to propagate before testing.

**What it does not create:** a private network, monitoring stack, GitHub
Environment, OIDC deployment identity, or dev/test/prod release pipeline
configuration. It does not update your local `.env`.
See [infrastructure details](infra/README.md).

The ignored `.azure` directory stores azd environment settings. Re-running
`azd up` reconciles infrastructure and deploys the current Python/container
changes as a new agent version. For code-only changes, use
`azd deploy math-tutor --no-prompt`; use `azd provision --no-prompt` when you only
want infrastructure. Do not use this developer deployment to independently
manage official dev/test/prod resources owned by GitHub workflows.

After deployment, verify the agent and make one live, billable test request:

```powershell
azd ai agent doctor
azd ai agent show --output json
azd ai agent invoke "Find the area of a rectangle 3 cm by 4 cm."
```

Use the authenticated Foundry endpoint printed by `azd`, not the local
`chat.py` URL, to access the cloud agent.

### 4. Configure the model

Copy these two values from `azd env get-values` into your `.env`, or use the
equivalent settings for your existing model deployment:

```dotenv
AZURE_OPENAI_ENDPOINT=https://<foundry-account-name>.openai.azure.com/
AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-5-mini
DEFAULT_AD_PORT=8088
ENABLE_SWAGGER=true
```

`AZURE_AI_MODEL_DEPLOYMENT_NAME` selects the deployed model. This repository
names provisioned deployments exactly after `modelName` (`gpt-5-mini` by default).
For an existing externally managed deployment, use its actual deployment name.
The OpenAI resource endpoint is not the Foundry project endpoint.
Leave the legacy `AZURE_OPENAI_API_ENDPOINT` and `MODEL_DEPLOYMENT_NAME` aliases
blank when using these canonical settings.

Existing environments that deployed the model as `math-tutor` will create a
new `gpt-5-mini` deployment on the next provision. The old deployment is not
renamed or automatically deleted and continues to reserve quota. The hosted
agent receives the new deployment name from provisioning outputs; update the
local `.env` value yourself after provisioning and restart the local server.
Keep the old deployment until its consumers have migrated and the new one is
verified. The hosted agent and Foundry project remain named `math-tutor`.

Authentication uses `DefaultAzureCredential`; your local `az login` identity
must have model-invocation access. No API key is needed. Process environment
values take precedence over `.env`. Never commit `.env` or credentials.

### 5. Start the server, then the chat client

In **terminal 1**, activate the virtual environment and start the Responses
server:

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

In **terminal 2**, check readiness and start the chat client:

```powershell
.\.venv\Scripts\Activate.ps1
Invoke-RestMethod http://localhost:8088/readiness
python chat.py
```

Try: `Find the area of a rectangle 3 cm by 4 cm.` Then ask a follow-up question.
Live questions invoke the Azure model and incur usage charges; readiness does not.

The server listens on port 8088 by default. The chat client calls its
`/readiness` and `/responses` endpoints; it does not create an agent or call
Azure directly. All model settings and Azure credentials are used by the server.
Both programs load `.env` without overriding process environment values.
`PORT` takes precedence over `DEFAULT_AD_PORT` for both server and client.
Use `python chat.py --url http://localhost:8090` to select a different server.

The CLI supports `help`, `status`, `clear`, and `quit`. Conversation history is
maintained by the server using stored response IDs. `clear` starts a new
conversation; it does not delete earlier responses from server storage.
`status` checks readiness, not live model access. Failed requests report an
error and preserve the last successful conversation response.

Press F5 and select **Math Tutor Foundry Hosted Agent** to debug the server.
Then run the chat client in another terminal, or select
**Math Tutor Chat Client (start server first)** in a second debug session.

If the client cannot connect, check that `main.py` is running and that both
programs use the same port. For authentication/authorization errors during a
question, check `az login`, the two model settings, and model-invocation RBAC.
Inspect server logs for model, quota, or tool errors.

#### Local failure diagnostics

The hosting SDK intentionally hides exception details when sensitive-data
capture is disabled. To investigate a generic `server_error` without recording
prompts or model responses, enable metadata-only diagnostics in the server
terminal. From the repository root in Windows Command Prompt:

```bat
set "ENABLE_LOCAL_DIAGNOSTICS=true"
.\.venv\Scripts\python.exe -u main.py > .venv\agent-local.log 2>&1
```

In PowerShell, set `$env:ENABLE_LOCAL_DIAGNOSTICS = "true"` before running the
same Python command. Stop an existing local server with Ctrl+C before starting
its replacement. Leave the replacement running; output is redirected to the log.
Use the chat client in another terminal to reproduce once (a paid model call),
then extract the metadata lines:

```bat
powershell -NoProfile -Command "Select-String -Path .venv\agent-local.log -Pattern local_agent_failure -SimpleMatch"
```

Diagnostics default to false and accept only `true` or `false`. When enabled,
failures retain their normal error behavior and emit a `local_agent_failure`
JSON line to stderr, bypassing telemetry logging handlers. It contains a trace
ID when available, exception-chain types, stack filenames/functions/line numbers
(no source lines or locals), numeric HTTP status codes, and recognized provider
error codes. Unknown provider codes and all exception messages, response bodies,
headers, prompts, and tool arguments are omitted. No model calls are made just
by enabling the setting. The middleware covers streaming and non-streaming runs.

The application does not export these diagnostic lines, but a host can still
collect stderr. Keep this option disabled in hosted environments. Other SDK log
lines follow their own telemetry settings; do not enable global sensitive-data
capture or share the whole log. The local file stays under the ignored virtual
environment directory. After troubleshooting, stop the server, set
`ENABLE_LOCAL_DIAGNOSTICS=false`, and restart it normally.

#### Swagger on the same local server

Set `ENABLE_SWAGGER=true` in `.env`, restart `python main.py`, and open
<http://localhost:8088/docs>. Swagger documents the actual hosted endpoints,
including `POST /responses` and `GET /readiness`, on the same port. There is
no second API or server.

Use **Try it out** on `POST /responses` with `stream: false` for an interactive
JSON result. This invokes the configured model and can incur Azure charges.
Set `store: true` and supply the returned ID as `previous_response_id` on a
later request to continue the conversation. Swagger documents the commonly
used request fields; the SDK remains responsible for the complete protocol.

`ENABLE_SWAGGER=false` disables both `/docs` and `/openapi.json`; false is
the default when the variable is absent. Only `true` and `false` are accepted
(case-insensitive). Process environment values override `.env`. Keep it false
in hosted/dev/test/prod deployments unless deliberately exposing documentation.
Swagger UI loads pinned JavaScript/CSS from jsDelivr, so the browser needs
internet access; API requests and the OpenAPI schema use this same local server.

### 6. Validate and ship a feature

```powershell
python -m pip check
python -m pytest -q
```

Offline tests require no Azure credentials or model calls. Keep numerical logic
in [operations/](operations/), typed wrappers in [tools/](tools/), and register
tools in [tools/catalog.py](tools/catalog.py). Add regression tests, then test
the change through the server and chat client.

Use a short-lived `feature/<description>` or `fix/<description>` branch and
open a pull request into `main`. **Build and Test Container** checks pull requests
without Azure credentials. After merge, **Create or Update Azure Resources**
reconciles dev, **Build, Test, and Publish Container** produces one tested image,
and **Deploy Container** consumes that successful build's digest without
rebuilding. Building and deployment are separate workflow runs. Use that same
**Deploy Container** workflow for manual dev deployments and test/prod
promotions, selecting the environment and approved source run.
Protect `main` with required checks and block direct/force pushes; GitHub
Environment approvals govern cloud deployment rather than environment branches.
Test and prod are explicit promotions of that
same image, not workstation `azd up` commands. Follow the
[feature release runbook](ci-cd.md#6-implement-a-feature-local---dev---test---prod)
for exact triggers, test gates, run-ID inputs, and rollback.

The container uses a digest-pinned Python base and a hash-verified Python 3.11
Linux dependency lock. Application-only copies exclude local configuration and
deployment artifacts. See [dependency updates](ci-cd.md#dependency-and-base-image-updates)
for regenerating locks and reviewing base/action updates.

## Microsoft Foundry hosted agent

See [endpoints.md](endpoints.md) for endpoint details, sample requests/responses,
streaming, conversation continuation, and a PowerShell walkthrough.

Local development and the container both start [main.py](main.py), which wraps
the tutor and all 24 tools with Microsoft's `ResponsesHostServer`.
This is the only application server. There is no separate REST API,
`/chat`, or `/calculate` endpoint. Optional Swagger at `/docs` documents these
same hosted routes when `ENABLE_SWAGGER=true`. Use [chat.py](chat.py) to send local requests
to `/responses`; calculations are tools invoked by the hosted agent.

| Hosted container endpoint | Contract |
|---|---|
| `POST /responses` | OpenAI-style Responses input and output; JSON or SSE via `stream` |
| `GET /readiness` | SDK readiness probe; HTTP 200 when the server is ready |
| `GET /responses/{response_id}` | Retrieve a stored response |
| `DELETE /responses/{response_id}` | Delete a stored response |
| `POST /responses/{response_id}/cancel` | Cancel a background response |
| `GET /responses/{response_id}/input_items` | Retrieve input items |

The SDK binds `0.0.0.0:8088`. `PORT` overrides the default; `DEFAULT_AD_PORT`
remains supported as a lower-priority local alias. Always
keep 8088 for the supplied container configuration. Model configuration is
required at startup; the service never silently starts in calculation-only
mode. Readiness is a process/configuration check,
not proof that Azure RBAC or the model deployment works.

```powershell
python main.py
```

Send this body to the local `http://localhost:8088/responses` endpoint:

```json
{"input": "Find the area of a rectangle 3 cm long and 4 cm wide.", "stream": false}
```

Use `"stream": true` for server-sent events. The SDK performs message conversion
and response lifecycle event formatting; no hand-written Responses emulation is
used. The host supplies conversation history and manages response/session storage.
Use `previous_response_id` with stored responses to continue a conversation, or
provide prior turns in `input`. The per-request agent factory isolates mutable
agent instances, and the inner model client uses `store=False` so history is not
stored independently in two systems.

### Dependency compatibility

[requirements.txt](requirements.txt) contains runtime dependencies only.
[requirements-dev.txt](requirements-dev.txt) adds the debugger and offline tests.

The old January-preview stack was upgraded with user approval to:

| Package | Version |
|---|---|
| `agent-framework-core` | `1.23.0` |
| `agent-framework-openai` | `1.17.0` |
| `agent-framework-foundry-hosting` | `1.0.0b261022` |
| `azure-ai-agentserver-core` | `2.2.0` |
| `azure-ai-agentserver-responses` | `2.3.0` |

The tutor now uses `Agent`, `AgentSession`, `tool`, and `OpenAIChatClient`;
`ChatAgent`, `AgentThread`, and the old function-invocation decorator were removed.
The legacy `azure-ai-agentserver-agentframework` adapter and Azure Projects SDK
are no longer dependencies. The tutor continues calling the same configured
Azure OpenAI resource and model deployment; no model is switched or provisioned.
Update Framework and hosting packages as a compatible set and run `pip check`
and the offline suite after changes.

The SDK exposes background-response APIs, but resilience across an ungraceful
process crash is not enabled by this starter. Configure durable state and the
SDK's resilient-task support before relying on long-running background work.
Default response/session stores use `AGENTSERVER_STATE_ROOT`, or
`~/.agentserver` when unset. Local container state is not a substitute for a
properly configured durable deployment.

### Container and deployment prerequisites

```powershell
docker build --platform linux/amd64 -t math-tutor-api:latest -f dockerfile .
docker run --rm --env-file .env -p 8088:8088 math-tutor-api:latest
```

Foundry requires a `linux/amd64` image in Azure Container Registry. The hosted
agent definition must declare Responses protocol **2.0.0**:

```yaml
protocols:
  - protocol: responses
    version: 2.0.0
```

The agent identity needs model-invocation permissions on the model resource;
the Foundry project's identity needs permission to pull the ACR image. Local
Azure CLI credentials are not automatically available inside Docker.
Configure Azure authentication for the environment; do not bake credentials
into the image.

After registration, invoke the agent through Foundry's authenticated endpoint.
Locally, the same hosted Responses protocol is available on port 8088.

### Infrastructure

[infra/](infra/README.md) contains Bicep templates for a modern Foundry account,
a Foundry project, and a Basic Azure Container Registry. They enable managed
identities and grant the project image-pull access to the registry, with key
authentication and registry admin credentials disabled. Public endpoints are
enabled. See the infrastructure guide for parameters, validation, deployment
commands, and deployment-identity permission bootstrap.

The azd developer bootstrap and the GitHub Actions resource-group deployment
path have different scopes. Model provisioning, image publishing, hosted-agent
registration, and live agent verification are separate lifecycle steps.

For the recommended GitHub Actions deployment model across local, dev, test,
and prod, see [CI/CD strategy](ci-cd.md). It covers build-once image promotion,
OIDC identities, environment approvals, testing, and rollback.

Official references:

- [Hosted agents and protocol choices](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents)
- [Hosted agent deployment and container requirements](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent)
- [Current Agent Framework hosting SDK](https://github.com/microsoft/agent-framework/tree/main/python/packages/foundry_hosting)
- [Official local-tools Responses 2.0 sample](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/hosted-agents/agent-framework/responses/02-tools)

## Project layout

- [agents/tutor_agent.py](agents/tutor_agent.py): tutor instructions and registration.
- [operations/](operations/): numerical calculations and validation.
- [tools/](tools/): typed agent tools registered through
  [catalog.py](tools/catalog.py).
- [main.py](main.py): local and Foundry Responses server and health probes.
- [server_docs.py](server_docs.py): opt-in Swagger/OpenAPI for that same server.
- [chat.py](chat.py): interactive HTTP client for the Responses server.
- [tests/](tests/): offline calculation and integration tests.

## Tests

```powershell
python -m pytest -q
```

Tests do not require Azure credentials or make model calls. Hosted protocol tests
exercise the actual pinned SDK adapter with mocked agent responses, including
non-streaming JSON, SSE, history input, and health probes. A live model invocation
and deployment smoke test still require Azure configuration.
Client tests also exercise HTTP failures, response validation, conversation
continuation and reset against the real host adapter without live model calls.

## Guided changes with the DevOps Assistant

The repository includes a read-only
[DevOps Assistant](.github/agents/devops-assistant.agent.md) for making changes
to the math tutor one step at a time.

1. Open this repository in VS Code with GitHub Copilot enabled.
2. Open Chat, select **DevOps Assistant** from the agent selector, and start a
   new conversation. If it is not listed, use **Chat: Open Customizations** in
   the Command Palette, check the workspace Agents list and any configuration
   diagnostics, and confirm the current checkout contains the agent file.
3. Describe one change and an example of the expected result, such as:
   "Guide me through adding a percentage tool. Give me only the next step."
   If you have not named a feature, the assistant first asks "What feature are
   we building?" It confirms the scope and an example of success with you
   before guiding branch preparation or code changes.
4. Perform each suggested action yourself and share the requested redacted
   result. The assistant explains the next step only after reviewing it.
5. After confirming the active feature branch and required local setup, the
   assistant tells you to switch to the default coding agent in the Chat
   selector (often labeled **Agent**). Copy its implementation brief into that
   chat; it includes the agreed scope, acceptance examples, branch, project
   conventions, and testing requirements. The coding agent is instructed not
   to commit, push, create a PR, or deploy.
6. Return to **DevOps Assistant** with the implementation summary and actual
   test results for local runtime testing and the remaining delivery steps.
   The assistant guides this manual switch; it never launches another agent
   or assumes that a new chat inherited the previous conversation.

For delivery, the assistant explains how you trigger and monitor the existing
workflows using GitHub Actions or user-run `gh` commands. It distinguishes
automatic PR/main triggers from manual runs, supplies the confirmed environment
and source-run inputs, and checks each result before guiding promotion. It
does not dispatch workflows itself or substitute `azd up` for GitHub delivery.

The assistant can read and search workspace context. It cannot edit files,
run commands or tests, create commits or PRs, delegate to another agent, or
make model calls or deployments. Code and commands it presents are suggestions
for you to review and execute, not actions it has performed.

To check the role, ask it to run the tests or deploy the agent: it should
explain its guide-only boundary and offer the next user-performed step instead
of attempting execution. The definition has no editing, terminal, cloud, or
delegation tools and does not request a particular model.

Tool restrictions depend on the selected host honoring the configuration.
Verify the available tools and actual activity in your VS Code session;
agent instructions are not a security sandbox and do not replace GitHub
permissions, branch protection, or environment approvals. This customization
does not change the hosted math tutor, its container, or the delivery workflows.

## Docker

```powershell
docker compose up --build
```

Docker Compose and the image both run `main.py`, serving the Foundry Responses
protocol on port 8088 with `/readiness` as the health check. After startup, use
`python chat.py` on the host to connect. Compose sets `PORT=8088` to match its
port mapping. Azure credentials must be configured inside the container; your
host's Azure CLI login is not automatically shared with Docker.
The image defaults to `math-tutor-api:latest`; override `DOCKER_REPO_NAME` to use
your own registry repository.

If you still see the old Swagger UI on port 8989/8990, an older process or image
is still running; it is not served by this application. Stop that specific old
server, or rebuild/recreate this project's container with `docker compose up
--build -d`. Do not stop unrelated containers. The current server exposes only
the hosted SDK routes listed above, with optional documentation on that same
server at port 8088 when enabled.
