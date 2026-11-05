# CI/CD for the Math Tutor hosted agent

## Recommendation

**Build once, publish to ACR, and promote the same image through dev, test, and
prod. Use GitHub Actions for official cloud deployments and keep the workstation
inner loop local.**

ACR is an image registry, not an agent runtime. Publishing an image does not
deploy or update a running agent. Foundry creates an agent version referencing
that image, with environment-specific configuration, identity, and compute.

These are separate pipeline stages, not necessarily separate manual operations:

```text
Workstation -> pull request -> offline CI + container checks
                                 |
                              merge main
                                 |
                      reconcile dev infrastructure + model
                                 |
                      build linux/amd64 image once
                                 |
                      scan + publish to dev ACR
                                 |
                      record immutable image digest
                                 |
                      deploy dev Foundry + smoke test
                                 |
                       approval / promotion request
                                 |
                  copy image to test ACR, without rebuilding
                                 |
                      deploy test Foundry + numeric smoke
                                 |
                      release qualification / evaluations
                                 |
                        production approval
                                 |
                  copy image to prod ACR, without rebuilding
                                 |
                      deploy prod Foundry + smoke test
```

The repository-side workflows and offline orchestration tests are now
implemented. Cloud jobs fail closed until the GitHub repository, protected
Environments, OIDC identities, Azure targets, and enablement flags are configured.
CI and Release can still be triggered on main before that setup is complete;
the existence of workflow files does not mean hosted-agent delivery is
commissioned. See [bootstrap](#10-bootstrap-the-implemented-workflows).

For day-to-day instructions, jump to
[Implement a feature: local -> dev -> test -> prod](#6-implement-a-feature-local---dev---test---prod).

### Understand the two deployment paths

| Path | Command/trigger | Creates or changes | Does not do |
|---|---|---|---|
| Developer deployment | Root `azd up` | Resource group, public Foundry account/project, model, developer model role, ACR, remote image build, hosted agent | Configure GitHub protections/OIDC, promote a tested digest, or rehearse production rollback |
| Official infrastructure | Release invokes Infrastructure for dev; manual Infrastructure `plan`/`apply` for test/prod | Resource group, public account/project, ACR, image-pull role/connection, pinned model by default | Build/publish an application image or register an agent |
| Agent release | Release / Promote / Rollback workflows | Dev infrastructure reconciliation, immutable image publication/promotion, Foundry versions, runtime model role and endpoint selection | Create GitHub Environments/OIDC identities, rebuild images during promotion, or automatically change test/prod infrastructure |

[azure.yaml](azure.yaml) defines the developer `math-tutor` hosted service.
[infra/azd/main.bicep](infra/azd/main.bicep) provisions its infrastructure;
[infra/main.bicep](infra/main.bicep) and
[environment parameters](infra/environments/) support the official
infrastructure workflow. An azd environment named `dev` or `math-tutor-dev`
does not configure the GitHub `dev` Environment. If reusing developer-provisioned
resources for shared dev, explicitly adopt their IDs/names in the infrastructure
configuration, configure CI/runtime permissions, and stop independently
deploying with azd before running Release. Avoid two independent owners
reconciling the same infrastructure or agent endpoint.
For an existing azd endpoint using `@latest`, set `ADOPT_EXISTING_VERSION` to
its currently active latest numeric version (for example `2`, after verifying
the current Azure state). The adapter verifies the value and unchanged selector, then
pins that version **before** creating a candidate. It will not silently adopt
latest routing. Remove the variable after a successful handoff.

## 1. Environments and resource isolation

| Environment | What runs there | Infrastructure/configuration | Trigger and gate |
|---|---|---|---|
| Local workstation | `main.py` Responses server on 8088; `chat.py` HTTP client; offline tests | `.venv`, ignored `.env`, developer Azure login, non-production model; Docker optional | Run locally while editing; no ACR push or agent deployment |
| Dev | Hosted agent version using the new release image; candidate and endpoint numeric smoke tests | Dedicated resource group, account/project, model, ACR, GitHub `dev` variables/OIDC | Merge to main or manual Release on main; CI, published-image startup, HIGH/CRITICAL scan, live smoke |
| Test | Hosted agent using the same digest imported from dev; qualification testing | Separate resource group, account/project, model, ACR, GitHub `test` variables/OIDC | Manual Promote with successful dev Release run ID; provenance/digest checks and live smoke; broader release qualification before prod |
| Prod | Hosted agent using the same digest imported from test; synthetic smoke | Isolated production account/project, model, ACR and identities; separate subscription where practical | Manual Promote with successful test promotion run ID; configured Environment reviewers and both deployment flags; live smoke |

Use the same Bicep template with separate parameter files for each cloud
environment. An environment name is not an isolation boundary by itself: its
resource IDs, identities, endpoints, quotas, and access controls must differ.
Do not use production resources, credentials, or student conversations locally.

**Registry choice:** start with one ACR per cloud environment. This matches
[the existing infrastructure](infra/main.bicep), isolates production image
storage, and avoids making production restarts dependent on a dev registry.
Build into dev ACR, then import/copy the approved image into test and prod ACR
by digest. Verify the destination manifest digest matches the recorded source
digest; fail promotion on a mismatch. Preserve the OCI manifests and required
layers, and explicitly transfer/verify signatures or attestations if used.

A dedicated shared build/artifact ACR is a useful later option for multiple
applications or stronger build isolation. One shared ACR for all environments
is also cheaper, but increases the shared access and availability boundary.
Neither option justifies rebuilding the application for each environment.

## 2. Three independent lifecycles

### Infrastructure

Infrastructure remains its own job and uses its own OIDC identity. Every
Release reconciles dev infrastructure after CI and before image publication:
validate, what-if, then incremental ARM deployment. Existing resources are
updated/reused, not torn down and recreated. Infrastructure changes can incur
costs or affect availability; review IaC/model changes in the PR and configure
the dev Environment's approval policy accordingly.

Test/prod infrastructure remains a separate protected manual operation.
Run Infrastructure `plan`, review its what-if, then `apply` before promotion.
The plan operation requires an existing group; apply can create a missing
group if the infrastructure identity has subscription-level group-creation
permission. Precreating groups permits narrower role scopes.

The [infrastructure guide](infra/README.md) describes the template's scope.
It provisions an ACR connection and optionally an explicitly versioned model.
Separate dev/test/prod parameter files are included. The workflow enables the
pinned model by default. CI federation and monitoring remain bootstrap tasks;
deployment now grants model access to the actual hosted instance identity
before candidate smoke, using the same helper as azd.

### Image build and publication

Build [dockerfile](dockerfile) from the reviewed commit on a trusted Linux
GitHub Actions runner, explicitly targeting `linux/amd64`. Use Buildx for the
standard CI path. ACR Tasks is an alternative remote builder, particularly when
a workstation has no Docker daemon; choose one release build path rather than
building twice.

Run dependency checks and tests, build the image, check its startup and hosted
contract, scan it, and publish the approved candidate to ACR. Some scanners
require an image to be pushed first; in that case, keep it an unapproved
candidate until scanning succeeds. Publication alone must never trigger
production rollout.

Use a unique tag incorporating the commit and GitHub run/attempt, for example
`sha-<commit>-run-<run-id>-<attempt>`. A commit alone is insufficient because
rebuilding the same commit with a newer base image can produce different bytes.
Capture the registry's image digest as the release identity:

```text
<registry>.azurecr.io/math-tutor@sha256:<digest>
```

Prefer deploying the digest reference. If a selected deployment tool requires
a tag, use a unique write-protected tag and verify its resolved digest before
deployment. Never release with mutable `latest`, `dev`, `test`, or `prod` tags.
Retain active and rollback images and protect them against deletion as well
as overwriting.

Record a release manifest containing commit, workflow run, digest, platform,
scan/SBOM/provenance references, and the deployment-definition revision.
Promotion consumes this record, not an arbitrary user-supplied image.

Build once does not mean dependencies can remain unpatched. Update dependencies
and base images deliberately, producing a new candidate and running the gates
again. The current base image and some dependencies are not fully locked;
pin the base digest and establish dependency locking as pipeline hardening.

### Foundry deployment

For each environment:

1. Verify the approved image is available in its ACR and accessible to Foundry.
2. Resolve the environment's project, model settings, identity, and compute.
3. Create a Foundry hosted-agent version referencing that exact image.
4. Wait for the version to become active, with a bounded timeout.
5. Test the candidate version before selecting it for the client-facing agent
   endpoint. Verify the deployed definition resolves to the expected image.
6. Select the approved version for the endpoint and test through that endpoint.
7. Record the environment, image digest, Foundry version, configuration revision,
   model deployment/version, and previous known-good version.

Microsoft's quickstart uses Azure Developer CLI (`azd`), which remains useful
for interactive development. The implemented release path deliberately uses
[a small deployment adapter](scripts/delivery.py) against the documented
Foundry REST `v1` API, authenticated through Azure CLI/OIDC. This keeps digest
references, pinned candidate sessions, endpoint selection, and rollback
explicit, with no packaging/build command in promotion. It also avoids
depending on preview CLI extension behavior for release gating.

The root `azure.yaml` owns developer infrastructure and hosted-agent versions.
The GitHub adapter owns official agent versions and endpoint selection.
Do not point azd and the adapter at the same official agent without a deliberate
ownership handoff and coordinated endpoint state. An existing
agent must have a concrete 100% version pin, or an explicit
`ADOPT_EXISTING_VERSION` matching its current `@latest` target. Other implicit
or split routing is refused rather than risking a change during testing.
A brand-new agent is provisioned without existing users and pinned as soon as
it becomes active, before smoke tests; its initial route is not an isolated
production rollout. A failed first smoke leaves that concrete bootstrap pin in
place so permissions can be fixed and a later candidate deployed safely.

## 3. Recommended GitHub Actions structure

These workflows are implemented:

| Workflow | Trigger | Responsibility |
|---|---|---|
| [ci.yml](.github/workflows/ci.yml) | Pull requests, main pushes, reusable call | Python 3.11 tests, dependency checks, actionlint, Bicep compilation, container startup checks; no Azure credentials on PRs |
| [infrastructure.yml](.github/workflows/infrastructure.yml) | Reusable call; manual `plan` or `apply` | Validate/what-if and reconcile resources/model; publish configuration outputs |
| [release.yml](.github/workflows/release.yml) | Main push or manual main run | Run CI, reconcile dev infrastructure, build/publish/scan one image, create manifest, deploy/test dev |
| [promote.yml](.github/workflows/promote.yml) | Manual source run ID | Verify source-run provenance, copy by digest, deploy test or prod |
| [deploy.yml](.github/workflows/deploy.yml) | Reusable workflow | Environment gates, runtime model role, candidate smoke, endpoint selection, evidence |
| [rollback.yml](.github/workflows/rollback.yml) | Manual known-good run ID | Verify source-run provenance and restore a recorded version |

Share deployment logic through a reusable workflow so dev/test/prod execute
the same steps. Dev infrastructure, image build, and Foundry deployment are
ordered jobs in one release. Test/prod infrastructure is separately approved.
More workflow files are not
inherently safer than clear responsibilities and permissions.

Use GitHub Environments named `dev`, `test`, and `prod`. Set branch/tag
restrictions, production reviewers, and prevention of self-approval where
available under the repository's GitHub plan. Protect workflow/IaC changes with
required reviews and CODEOWNERS. Use a protected main branch and short-lived
feature branches rather than long-running branches for every environment.

Serialize deployment per environment/agent with a concurrency group. Do not
cancel a production deployment mid-rollout because another commit arrived.
Set explicit timeouts, fail on deployment or evaluation errors, and publish a
deployment summary. Promote an identified successful release, not whatever
commit happens to be at the branch tip when the promotion job starts.

## 4. Authentication and least privilege

Use GitHub OIDC federation to Azure, not client secrets, registry passwords,
or a developer's cached login. Grant `id-token: write` only to jobs that need
Azure authentication, and `contents: read` by default. Pin third-party actions
to reviewed full commit SHAs and update them through reviewed dependency PRs.

Configure federated credentials for the actual repository and protected
environment claims. Do not blindly copy a `repo:owner/name:environment:prod`
subject: GitHub supports immutable ID-based subjects and the actual subject
depends on repository settings/history. Inspect the emitted claims and match
the configured subject and audience exactly.

| Identity | Needed access | Must not imply |
|---|---|---|
| PR CI | Repository contents; no Azure access | Permission to publish or deploy |
| Release builder | Push to build registry/repository; appropriate Tasks permissions only if using ACR Tasks | Production agent management or infrastructure administration |
| Promotion identity | Read approved source images and import/write target images | General subscription administration |
| Environment agent deployer | Foundry project deployment permissions, resource reads, and constrained assignment of the model-user role on its account | Infrastructure-wide Owner access |
| Infrastructure deployer | Resource creation and scoped role-assignment management | Routine application workflow privileges |
| Foundry project managed identity | Pull the environment's image | Image publishing or runtime model permissions |
| Platform-created agent runtime identity | Invoke the configured model and explicitly allowed tools | CI/deployment privileges |

For the current registry-level RBAC mode, `AcrPush`/`AcrPull` are relevant.
Repository-level ABAC uses different roles: do not mix the two models.
Production registry write access belongs to promotion automation, not developer
workstations. Keep production federation separate from dev/test federation.

Use the current Foundry permissions reference to choose deployment roles
(currently Foundry Project Manager for hosted-agent deployment); validate actual
required operations rather than assigning subscription Owner to make CI pass.
Bootstrap role-assignment/federation setup is privileged and separate from the
normal application pipeline.

The agent code currently uses `DefaultAzureCredential` and a direct Azure
OpenAI resource endpoint. Validate that authentication works with the actual
Foundry-injected runtime identity, and grant access on that specific model
resource. Default platform access through a project endpoint is not proof that
this application's direct-resource call will succeed.

Never run untrusted PR code with deployment credentials, including through
`pull_request_target` or an unchecked privileged follow-up workflow. Treat
release inputs as data, validate them, and verify artifact provenance before
running privileged promotion jobs.

## 5. Environment configuration, not environment-specific images

Keep the image identical and inject configuration at deployment time.

| Setting | Source |
|---|---|
| Subscription, resource group, location, project ID/endpoint, registry | Environment-scoped GitHub variables and infrastructure outputs |
| Azure OIDC client/tenant/subscription IDs | GitHub variables; these IDs are not passwords |
| `AZURE_OPENAI_ENDPOINT` | Environment's model resource endpoint, not the Foundry project endpoint |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Environment's explicit model deployment |
| Port/protocol | Container port 8088; Responses `2.0.0` |
| Python startup | Set `PYTHONNOUSERSITE=1` in the hosted version's runtime configuration per current Foundry guidance |
| Message-content capture | Keep `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false` unless explicitly reviewed |
| Local Swagger | `ENABLE_SWAGGER=false` by default; enable `/docs` on the same server only for local testing |
| Genuine secrets, if introduced | Managed connection/secret store with runtime identity; never image layers or build arguments |

Do not copy `.env`, credentials, or local identity caches into an image. Review
[.dockerignore](.dockerignore) before enabling CI publication. Do not override
platform-injected agent identity/context variables.

Store non-secret configuration and model policy in version control. Test should
match production's model family/version and relevant settings closely enough
to qualify behavior; dev may use cheaper settings, but cannot substitute for
production-equivalent evaluation. Record model/settings changes as releases
even when the container digest stays unchanged.

## 6. Implement a feature: local -> dev -> test -> prod

### Before your first feature

Complete the [README getting-started guide](README.md#getting-started) for
Python, model access, and local configuration. Complete
[workflow bootstrap](#10-bootstrap-the-implemented-workflows) once for each
cloud environment before attempting its first official release. A successful
developer `azd up` is not GitHub pipeline commissioning: the official release
still needs GitHub OIDC, protected environment variables, permission to assign
runtime model roles, and deployment gates. For an independent developer cloud
iteration, run `azd deploy math-tutor --no-prompt` and test with
`azd ai agent invoke`; this rebuilds an image and is not test/prod promotion.

The commands below assume this workspace is connected to its GitHub repository,
`main` is protected, and GitHub CLI is authenticated (`gh auth login`).
Replace placeholder run IDs with numeric GitHub Actions run IDs.

### A. Implement and test locally

1. Create a short-lived feature branch:

   ```powershell
   git switch -c feature/your-feature
   .\.venv\Scripts\Activate.ps1
   ```

2. Implement the change. Numerical logic belongs in [operations/](operations/),
   typed tool wrappers in [tools/](tools/), and shared registration in
   [tools/catalog.py](tools/catalog.py). Add regression tests; preserve
   Agent/AgentSession and the Responses protocol contract.
3. Run offline validation:

   ```powershell
   python -m pip check
   python -m pytest -q
   ```

4. For a live local test, use non-production model settings in `.env`, sign in
   with `az login`, and start the same entry point used by the container:

   ```powershell
   # Terminal 1, with .venv activated:
   python main.py
   ```

   ```powershell
   # Terminal 2:
   .\.venv\Scripts\Activate.ps1
   Invoke-RestMethod http://localhost:8088/readiness
   python chat.py
   ```

   Ask a question exercising the feature, a follow-up that checks conversation
   context, and an invalid-input case. `clear` starts a new conversation.
   Readiness is not a model/RBAC test; an actual question calls the model and
   incurs charges. Restart the server after changing Python code; it does not
   automatically reload. F5 **Math Tutor Foundry Hosted Agent** is an alternative
   to terminal 1.

Docker is an optional parity check. It uses `main.py` and port 8088 too, but
does not inherit your workstation Azure login. Do not run both Python and
Docker servers on the same host port. Local experiments must not overwrite
official test/prod agents or use student conversations.

### B. Open a PR and pass credential-free CI

Commit and push the feature branch, then open a PR targeting main:

```powershell
git push -u origin feature/your-feature
gh pr create --base main --title 'Describe your feature' --body 'Describe the change and test evidence.'
```

[CI](.github/workflows/ci.yml) runs offline Python tests, `pip check`,
actionlint, resource-group and azd Bicep/environment-parameter compilation, and Linux
container startup/readiness/malformed-input checks. It does not publish to ACR
or make live model calls. Azure credentials are not supplied to PR jobs.
Configure these checks as required branch protection; workflow files alone
do not enforce review or merge policy.

### C. Merge and deploy dev

Merge the reviewed PR after CI succeeds. [Release](.github/workflows/release.yml)
automatically runs on a main push; it can also be started manually on main.
It:

1. Calls CI again for the release revision.
2. Calls Infrastructure with `dev`/`apply` using the infrastructure identity:
   reconciles the resource group, public Foundry account/project, ACR/connection,
   and pinned model. Publishes `infrastructure-dev`.
3. Loads that run's infrastructure outputs directly into build and dev deploy;
   no manual copying of dev endpoints/registry IDs is needed.
4. Authenticates through the `dev` Environment's build identity.
5. Builds/pushes one `linux/amd64` release image into dev ACR with a unique tag.
6. Pulls that published digest for startup checks; blocks HIGH/CRITICAL scan
   findings, records an SBOM, and verifies/locks the release image.
7. Uploads the `release` artifact, then calls the reusable dev deployment.
8. Creates a Foundry candidate version, waits for it, grants its actual
   `instance_identity.principal_id` model invocation access, tests numeric behavior,
   selects it for the endpoint, tests the selected endpoint, and records the
   digest/version/configuration plus the previous selector.

Find the run and review all jobs, including **deploy-dev**:

```powershell
gh run list --workflow release.yml --branch main --limit 5
gh run view '<release-run-id>'
```

For an explicitly requested manual release:

```powershell
gh workflow run release.yml --ref main
```

Do not promote a build-only or failed run. Inspect `release` and
`deployment-dev` artifacts and exercise the feature in shared dev. The live
smoke set covers existing numeric cases; a new feature may need new smoke
assertions and additional test evidence. New role assignments can take time
to propagate. Only after a new assignment, candidate smoke retries HTTP
401/403/500/502/503/504 up to four times at 60-second intervals in fresh
sessions, logging each retry. Invalid numeric results, other errors, or an
exhausted retry budget fail the release; no failed candidate is promoted.

### D. Promote the successful dev release to test

Once dev succeeds and the **test infrastructure and GitHub Environment are
configured**, select that successful Release run's ID:

```powershell
gh workflow run promote.yml --ref main -f environment=test -f source_run_id='<successful-release-run-id>'
gh run list --workflow promote.yml --branch main --limit 5
```

[Promote](.github/workflows/promote.yml) verifies the source run's repository,
workflow, branch/event, successful result, and deployment record. It imports
the exact digest from dev ACR into test ACR, verifies/locks it without rebuilding,
and deploys with **test's** endpoint/model settings and permissions. Candidate
and selected-endpoint numeric smoke tests run again; evidence is uploaded as
`deployment-test`.

Qualify the feature in test: functional and invalid-input cases, streaming,
multi-turn behavior, model quality/safety, and latency/token budgets as
appropriate. Match production model/version/settings closely. These broader
qualification checks are **not all automated by the current workflows**;
record the results and obtain release approval before starting prod promotion.

### E. Promote the qualified test release to prod

Use the successful **Promote-to-test run ID**, not the original Release run ID:

```powershell
gh workflow run promote.yml --ref main -f environment=prod -f source_run_id='<successful-test-promotion-run-id>'
```

The prod job requires `DEPLOYMENTS_ENABLED=true` and
`PRODUCTION_DEPLOYMENTS_ENABLED=true` in the `prod` Environment. Required
reviewers/branch restrictions must be configured in GitHub; they are not created
by the YAML or by `azd up`. Review the test evidence and requested source run
before approving the waiting deployment.

The workflow imports the same digest from test ACR into prod ACR, deploys with
prod configuration, tests the candidate, selects the version, and tests the
selected endpoint. Review `deployment-prod`, monitor failures/latency, and keep
the previous known-good version/image available. Do not rebuild, retag `latest`,
or run workstation agent deployment commands to bypass this promotion.

The local `chat.py` client is not an authenticated Foundry cloud client.
Use the pipeline's authenticated smoke tests or the appropriate authenticated
Foundry tooling for cloud verification.

### F. Roll back or continue development

For a bad rollout, select an earlier successful deployment run for the **same
target environment**:

```powershell
gh workflow run rollback.yml --ref main -f environment=prod -f known_good_run_id='<earlier-successful-prod-run-id>'
```

[Rollback](.github/workflows/rollback.yml) verifies the recorded version,
restores its endpoint selection, runs smoke, and writes rollback evidence.
It does not rebuild or revert model/infrastructure changes. Existing sessions
can remain attached to their original versions. Artifacts and old versions
must still be retained.

For a code fix, repeat the feature branch -> PR -> dev -> test -> prod path.
For infrastructure/model changes, run the protected Infrastructure `plan`
and then `apply` workflow separately; ordinary Python commits do not provision
cloud infrastructure.

## 7. Gates and evidence

| Gate | Required evidence |
|---|---|
| Offline CI | All tests pass; dependency consistency; Bicep compiles; numerical/domain and tool contract regressions covered |
| Container | Correct architecture; startup succeeds with test configuration; `/readiness` returns 200; malformed Responses input fails correctly; no model request required |
| Supply chain | Approved image scan result, recorded digest, dependency/SBOM data, and provenance policy |
| Dev live smoke | Version active; authenticated Foundry call succeeds; real model and geometry tool execution confirmed |
| Test qualification | Same image digest; functional cases, streaming, conversation behavior, safety/quality evaluations, and latency/token budget checks pass |
| Prod rollout | Approval; same promoted image; endpoint targets the intended version; synthetic smoke succeeds; previous version recorded |

Readiness is not a model/RBAC test. A nonempty response or successful CLI exit
alone is not sufficient live-test evidence. Validate the response schema/status
and expected behavior. For example, a 3-by-4 rectangle should yield area 12 and a
radius-2 circle should yield approximately 12.56637 square units. Confirm tool
execution through controlled instrumentation/traces; a correct answer alone
could have been produced without calling a tool.

Use tolerances for numeric assertions, not exact natural-language sentence
matches. Test invalid dimensions and an algebra case, and check streaming
completion and multi-turn continuity. Use synthetic data with bounded retries,
timeouts, and spend; run a small safe smoke set in prod and broader evaluations
in test. Do not hide failures behind retries or automatically promote on
missing results.

Store test/evaluation results with the release record. Choose and document
quality, latency, and cost thresholds before enabling automatic promotion.
Do not label the offline mock-based tests as live Azure verification.

## 8. Rollback and operational readiness

Rollback selects the previous known-good Foundry version for the endpoint;
it does not rebuild old source or move a mutable image tag. If an old version
must be recreated, use its retained image digest and recorded configuration.
Verify endpoint behavior after rollback and record the deployment event.

Test a candidate version before switching the endpoint, and distinguish
version readiness from endpoint selection. Foundry version IDs are local to
each agent/project: dev version 3 need not correspond to prod version 3.
Existing sessions remain bound to their original version when the endpoint's
selected version changes; do not promise instantaneous migration or rollback
of every in-flight conversation. Rehearse this behavior with the chosen API.

Application rollback does not undo destructive infrastructure changes, altered
model availability, or incompatible state changes. Use compatible changes and
separate approvals. The current starter's local response/session storage and
background work are not a production durability guarantee; decide on supported
state/recovery behavior before advertising reliable long-lived conversations.

Before production, establish telemetry with restricted content access, failure
alerts, capacity/model quota checks, image retention, budgets, and an incident
runbook. Validate region/network support and runner connectivity. Private
endpoints, if adopted, require a runner/network path that can reach them.

## 9. Commissioning order for this repository

1. Choose environment subscriptions/regions, model deployments, the GitHub
   repository, and approval policy.
2. Bootstrap GitHub OIDC identities, protected Environments, and role scopes.
   Configure the included environment parameter files and workflow variables.
3. Review existing dev resource names and explicit ownership handoff settings,
   without duplicating existing resources.
4. Run Release to reconcile dev infrastructure/model, build the authoritative
   image, create a manifest, grant runtime model access, and test the candidate
   and selected endpoint.
5. Resolve any permission-grant, image-pull, quota, or API issues.
   Run actual model/tool verification before declaring dev commissioned.
6. Provision test and exercise the included digest-preserving promotion.
   Establish the broader model quality/safety evaluation policy.
7. Commission prod with protected approval, telemetry, retention, and a
   rehearsed rollback before enabling its additional deployment opt-in.

A successful developer `azd up` is evidence of that environment's infrastructure
and hosted-agent deployment; record a live invocation separately to verify
model/tool access. It is not evidence that GitHub Actions, protected promotion,
or rollback have run. Official pipeline commissioning remains separate.

## 10. Bootstrap the implemented workflows

### GitHub and Azure prerequisites

1. Create/import a GitHub repository with `main` as its default branch if not
   already connected. Local `azd up` does not create/push a repository or
   configure GitHub Actions.
2. Select public-cloud Azure subscriptions in the same Entra tenant, supported
   regions, and target resource groups for dev/test/prod. Precreate groups
   for narrowly scoped bootstrap roles, or authorize the infrastructure
   identity to create groups. Register the Cognitive Services and Container
   Registry providers using an authorized administrative process.
3. Create GitHub Environments `dev`, `test`, `prod`. Configure branch restrictions
   and reviewers before enabling deployment; reviewers require an appropriate
   GitHub plan/repository visibility. Require review of workflow changes too.
4. Create separate federated identities for infrastructure, dev image building,
   and each environment's application deployment. Match the repository's actual
   OIDC subject claims and `api://AzureADTokenExchange` audience. No passwords
   or Azure client secrets are required by these workflows.
5. Grant the infrastructure identity resource creation and constrained
   role-assignment permissions in its resource group. Grant the dev builder
   Reader and `AcrPush` at the dedicated dev resource group so a newly created
   registry inherits access. Grant each agent deployer the Foundry project
   deployment role plus Reader/`AcrPull` at its dedicated environment group,
   or the resulting project/registry scopes for preprovisioned environments.
   The deployer also needs role-assignment read/write at the model account,
   constrained to `Cognitive Services OpenAI User` assignments to service
   principals. Apply this scope/condition during privileged bootstrap;
   do not grant subscription Owner to routine deployment jobs.
   Test/prod promotion additionally needs source image read access, target
   `AcrPush`/metadata-write access, and the scoped
   `Microsoft.ContainerRegistry/registries/importImage/action` permission.
   Use a constrained custom role for import rather than subscription Owner.
6. Runtime role creation is automated: REST deployment and azd share
   [grant_model_access](scripts/delivery.py). It grants the actual hosted
   principal `Cognitive Services OpenAI User` on the same Foundry account.
   Ensure the deployer's constrained assignment permission is configured
   before the first release. This pipeline expects the model in the agent
   project's account; an external model account needs a deliberate extension.
7. For azd-created shared dev, configure exact existing resource names and
   `ADOPT_EXISTING_VERSION`, stop independent azd deployments, and review the
   handoff before enabling Release. No Azure endpoint is changed merely by
   editing these workflow files.

### GitHub Environment variables

All the following are non-secret configuration; define them under
**Settings > Environments > environment > Environment variables**.
Never commit actual credentials.

| Variable | Used by | Value |
|---|---|---|
| `DEPLOYMENTS_ENABLED` | All cloud workflows | Exact `true` only after environment protection/OIDC setup |
| `PRODUCTION_DEPLOYMENTS_ENABLED` | Prod deploy/rollback | Exact `true` only after production commissioning and quality review |
| `AZURE_TENANT_ID` | Azure login | Target tenant |
| `AZURE_SUBSCRIPTION_ID` | Azure login/infrastructure | Target subscription |
| `AZURE_INFRA_CLIENT_ID` | Infrastructure | Federated infrastructure application's client ID |
| `AZURE_BUILD_CLIENT_ID` | Dev release build | Federated builder's client ID |
| `AZURE_DEPLOY_CLIENT_ID` | Agent deploy/promotion/rollback | Environment's federated deployer's client ID |
| `AZURE_RESOURCE_GROUP` | Infrastructure | Target group; apply creates it when permitted |
| `AZURE_LOCATION` | Infrastructure | Confirmed supported region |
| `AZURE_AI_ACCOUNT_NAME`, `AZURE_AI_PROJECT_NAME` | Infrastructure | Optional existing-name overrides; otherwise stable template defaults |
| `AZURE_CONTAINER_REGISTRY_NAME` | Infrastructure / test/prod deploy | Optional existing registry name for infrastructure; output supplies dev jobs |
| `AZURE_CONTAINER_REGISTRY_ID` | Test/prod deploy | Exact registry ARM ID; dev consumes this run's output |
| `AZURE_AI_ACCOUNT_ID`, `AZURE_AI_PROJECT_ID` | Test/prod runtime role | Account/project ARM IDs from infrastructure; supplied automatically in dev |
| `AZURE_AI_PROJECT_ENDPOINT` | Test/prod deploy/rollback | Project endpoint; dev deploy/rollback consumes infrastructure artifacts |
| `AZURE_OPENAI_ENDPOINT` | Test/prod deploy | Same account's direct model resource endpoint, not the project URL; automatic in dev |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Model provisioning / test/prod deploy | Defaults to `math-tutor` when provisioning; automatic output in dev |
| `FOUNDRY_AGENT_NAME` | Agent deploy/rollback | Stable lowercase name; defaults to `math-tutor` |
| `ADOPT_EXISTING_VERSION` | Explicit ownership handoff | Current latest concrete version to pin before adopting an existing `@latest` endpoint; remove after handoff |
| `SOURCE_ACR_RESOURCE_ID` | Promotion | Dev ACR ID in test; test ACR ID in prod |
| `PROVISION_MODEL` | Infrastructure | Defaults to `true`; keep true for automatic dev; false only for separately configured infrastructure/model |
| `MODEL_NAME`, `MODEL_VERSION` | Model provisioning | Defaults `gpt-5-mini`, `2025-08-07`; review availability/quota |
| `MODEL_SKU`, `MODEL_CAPACITY` | Model provisioning | Defaults `GlobalStandard`, `1`; override with supported values |

Dev consumes its own `infrastructure-dev` artifact in the same Release run;
rollback downloads that artifact from the verified known-good Release run.
Only allowlisted, nonempty, single-line outputs are exported. No GitHub
variable-write token is needed. Dev deployment fails if required infrastructure
outputs are missing, including the model deployment.

For test/prod, copy the manual Infrastructure output artifact values into the
protected Environment variables before promotion. For a separately configured
model in that same account, set `PROVISION_MODEL=false` and explicitly configure
its endpoint/deployment. Environment location/model/name settings override the
selected Bicep parameter file; otherwise resource-name parameters are preserved.

### First deployment and promotion

1. Complete dev OIDC/role/environment bootstrap and review IaC/model settings.
   An optional manual `plan` can preview an existing group's changes.
   Run **Release** on main; it applies dev infrastructure before building.
   Approval happens before protected jobs, not between their what-if and apply.
2. Review all jobs and artifacts. A failed
   candidate remains recorded but is never eligible for promotion. Existing
   endpoint selection is preserved until candidate tests pass; failed endpoint
   smoke restores the prior selection when one exists.
3. Provision test the same way. Run **Promote**, selecting `test` and the
   successful Release run's numeric ID. No arbitrary image input is accepted.
4. After test qualification and production commissioning, provision prod and
   run **Promote** with the successful Promote-to-test run's ID. The adapter
   enforces dev -> test -> prod and verifies the source workflow, main branch,
   event, repository, successful conclusion, and deployment record.
5. To roll back, run **Rollback** with the environment and an earlier successful
   deployment run ID for that environment. Keep that version/image retained.
   A failed rollback endpoint smoke attempts to restore its original selector.

Imported images are verified and locked. Retrying promotion can reuse an
existing matching tag, but refuses to overwrite a different digest. Failed
agent versions are not deleted automatically. Existing sessions remain on
their original versions after selection or rollback.

### Current gates and honest limitations

- CI includes offline regression/orchestration tests, Bicep compilation,
  checksum-verified actionlint, and a Docker readiness/malformed-input check.
- Release checks the **published digest**, blocks all HIGH/CRITICAL Trivy
  findings (including unfixed ones), emits a CycloneDX SBOM, and locks the image.
  Remediate findings through reviewed updates; there is no success fallback.
- Promotion preserves the image manifest. Buildx embedded attestations are
  disabled to keep a single-platform image promotion contract; SBOM/scan and
  GitHub run evidence are stored as artifacts, not claimed as signed OCI
  attestations. Add a verified signing policy before requiring signed images.
- Live smoke asserts completed Responses and strict numeric results for
  geometry/algebra in candidate-specific and endpoint-selected sessions.
  It does **not** prove tool execution from traces or implement a comprehensive
  LLM quality/safety, streaming, latency, or cost evaluation suite. Those remain
  production commissioning requirements, so prod has an additional opt-in flag.
- Evidence artifacts are retained for 90 days (subject to repository policy).
  Promotion/rollback by run ID requires retained artifacts; export approved
  release records to durable storage for a longer operational window.
- Pinned actions/scanner/actionlint are included. Hosted runner Azure CLI/Bicep,
  the Python base image, and all transitive dependencies are not fully locked;
  review tool/base updates before relying on reproducible rebuilds.
- Local PyPI connectivity can differ from GitHub runners. The shared Dockerfile
  uses public PyPI and avoids BuildKit-only secret mounts so remote ACR builds
  also work. A private feed needs a separately reviewed secure build setup;
  never copy credentials into the image or pass them through build arguments.
- Developer `azd up` provisions and deploys the resources listed in
  [Getting started](README.md#3-deploy-public-foundry-acr-and-the-hosted-agent-with-azd).
  It does not commission GitHub workflows or rehearse production rollback.
  Verify live model/tool access with a separate invocation and record that
  evidence separately.

## Official references

- [Foundry hosted-agent deployment lifecycle and requirements](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent)
- [Microsoft's GitHub Actions/azd hosted-agent CI/CD quickstart](https://learn.microsoft.com/azure/foundry/agents/quickstarts/set-up-cicd-hosted-agent?pivots=azd)
- [Manage Foundry versions and endpoint selection](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent)
- [Hosted-agent permissions](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agent-permissions)
- [ACR image tagging and versioning best practices](https://learn.microsoft.com/azure/container-registry/container-registry-image-tag-version)
- [GitHub OIDC with Azure](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure)
- [GitHub deployment environments and protection rules](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)
