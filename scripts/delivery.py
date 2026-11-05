"""Build-once Foundry delivery using Azure CLI authentication and documented REST APIs."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID


ENVIRONMENTS = ("dev", "test", "prod")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
TAG = re.compile(r"sha-[0-9a-f]{40}-run-[0-9]+-[0-9]+")
MODEL_USER_ROLE = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Required configuration is missing: {name}")
    return value


def command(*args: str) -> str:
    executable = shutil.which(args[0])
    if executable is None:
        raise FileNotFoundError(f"Required command is not installed or not on PATH: {args[0]}")
    try:
        result = subprocess.run(
            (executable, *args[1:]), check=True, capture_output=True, text=True, timeout=300,
        )
    except subprocess.CalledProcessError as error:
        print(error.stderr, file=sys.stderr)
        raise
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.stdout.strip()


def azure(*args: str) -> dict:
    result = json.loads(command("az", *args, "--output", "json", "--only-show-errors"))
    if not isinstance(result, dict):
        raise ValueError("Expected an Azure CLI JSON object")
    return result


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def grant_model_access(scope: str, project: str, principal: str) -> bool:
    UUID(principal)
    account = re.fullmatch(
        r"/subscriptions/([^/]+)/resourceGroups/[^/]+"
        r"/providers/Microsoft\.CognitiveServices/accounts/[^/]+",
        scope, re.IGNORECASE,
    )
    if not account or not re.fullmatch(re.escape(scope) + r"/projects/[^/]+", project, re.IGNORECASE):
        raise ValueError("Expected the deployed project and model account in the same Foundry account")
    subscription = str(UUID(account[1]))
    assignments = azure(
        "role", "assignment", "list", "--scope", scope,
        "--subscription", subscription, "--query", "{assignments:@}",
    )["assignments"]
    if any(
        assignment["principalId"].lower() == principal.lower()
        and assignment["roleDefinitionId"].lower().endswith(f"/{MODEL_USER_ROLE}")
        and assignment["scope"].lower() == scope.lower()
        for assignment in assignments
    ):
        print("Hosted runtime model access is already configured.")
        return False
    azure(
        "role", "assignment", "create", "--assignee-object-id", principal,
        "--assignee-principal-type", "ServicePrincipal", "--role", MODEL_USER_ROLE,
        "--scope", scope, "--subscription", subscription,
    )
    print("Granted hosted runtime model access. Allow RBAC propagation before testing.")
    return True


def validate_release(release: dict) -> None:
    if release.get("schema_version") != 1 or release.get("repository") != "math-tutor":
        raise ValueError("Unsupported release manifest")
    for key, pattern in (("digest", DIGEST), ("commit", COMMIT), ("tag", TAG)):
        if not isinstance(release.get(key), str) or not pattern.fullmatch(release[key]):
            raise ValueError(f"Invalid release {key}")
    if release.get("platform") != "linux/amd64":
        raise ValueError("Only linux/amd64 releases are supported")
    if release.get("github_repository") != required("GITHUB_REPOSITORY"):
        raise ValueError("Release is from a different GitHub repository")
    if not str(release.get("build_run_id", "")).isdigit():
        raise ValueError("Invalid build run ID")
    if not release["tag"].startswith(f"sha-{release['commit']}-run-{release['build_run_id']}-"):
        raise ValueError("Image tag does not match release provenance")


def registry() -> dict:
    result = azure("acr", "show", "--name", required("AZURE_CONTAINER_REGISTRY_NAME"))
    if result["id"].lower() != required("AZURE_CONTAINER_REGISTRY_ID").lower():
        raise ValueError("Registry ID does not match configured environment")
    return result


def image_digest(image: str) -> str:
    result = azure(
        "acr", "repository", "show", "--name", required("AZURE_CONTAINER_REGISTRY_NAME"),
        "--image", image,
    )
    return result["digest"]


def lock_image(tag: str) -> None:
    command(
        "az", "acr", "repository", "update", "--name", required("AZURE_CONTAINER_REGISTRY_NAME"),
        "--image", f"math-tutor:{tag}", "--write-enabled", "false",
        "--delete-enabled", "false", "--only-show-errors",
    )


class Foundry:
    def __init__(self) -> None:
        self.base = required("AZURE_AI_PROJECT_ENDPOINT").rstrip("/")
        parsed = urlsplit(self.base)
        if (parsed.scheme != "https" or not parsed.hostname
                or not parsed.hostname.endswith(".services.ai.azure.com")
                or parsed.query or parsed.fragment or parsed.username or parsed.port
                or not re.fullmatch(r"/api/projects/[A-Za-z0-9_.-]+", parsed.path)):
            raise ValueError("Expected an Azure public-cloud Foundry project endpoint")
        self.agent = required("FOUNDRY_AGENT_NAME")
        if not NAME.fullmatch(self.agent):
            raise ValueError("Invalid Foundry agent name")
        self.token = azure(
            "account", "get-access-token", "--resource", "https://ai.azure.com",
        )["accessToken"]

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        if not path.startswith("/agents") or "?" in path or ".." in path:
            raise ValueError("Invalid Foundry API path")
        data = None if body is None else json.dumps(body).encode()
        content_type = "application/merge-patch+json" if method == "PATCH" else "application/json"
        request = Request(
            f"{self.base}{path}?api-version=v1", data=data, method=method,
            headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": content_type,
                "x-ms-user-isolation-key": f"ci-{required('GITHUB_RUN_ID')}",
            },
        )
        with urlopen(request, timeout=120) as response:
            payload = response.read(2_000_001)
        if len(payload) > 2_000_000:
            raise ValueError("Foundry response exceeded 2 MB")
        return json.loads(payload) if payload else {}

    @property
    def path(self) -> str:
        return f"/agents/{self.agent}"

    def get_agent(self) -> dict | None:
        try:
            return self.request("GET", self.path)
        except HTTPError as error:
            if error.code == 404:
                return None
            raise

    def wait(self, path: str) -> dict:
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            result = self.request("GET", path)
            status = result.get("status", "").lower()
            print(f"Foundry status: {status}", flush=True)
            if status == "active":
                return result
            if status != "creating":
                raise RuntimeError(f"Unexpected Foundry provisioning result: {result}")
            time.sleep(10)
        raise TimeoutError("Foundry did not become active within 15 minutes")


def concrete_version(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError("Expected a concrete released Foundry version")
    return value


def selector(version: str) -> dict:
    return {"version_selection_rules": [
        {"type": "FixedRatio", "agent_version": concrete_version(version), "traffic_percentage": 100}
    ]}


def selected_version(agent: dict) -> str:
    rules = agent["agent_endpoint"]["version_selector"]["version_selection_rules"]
    if len(rules) != 1 or rules[0].get("type") != "FixedRatio" or rules[0].get("traffic_percentage") != 100:
        raise ValueError("Endpoint must be pinned to exactly one version at 100%; bootstrap it first")
    return concrete_version(rules[0]["agent_version"])


def select(client: Foundry, version: str) -> None:
    client.request("PATCH", client.path, {"agent_endpoint": {"version_selector": selector(version)}})
    if selected_version(client.request("GET", client.path)) != version:
        raise RuntimeError("Endpoint version selection was not applied")


def deployment_previous_version(client: Foundry, agent: dict) -> str:
    rules = agent["agent_endpoint"]["version_selector"]["version_selection_rules"]
    latest = {"type": "FixedRatio", "agent_version": "@latest", "traffic_percentage": 100}
    if rules != [latest]:
        return selected_version(agent)
    version = concrete_version(required("ADOPT_EXISTING_VERSION"))
    if agent["versions"]["latest"]["version"] != version:
        raise ValueError("ADOPT_EXISTING_VERSION must match the current latest version")
    client.wait(f"{client.path}/versions/{version}")
    current = client.request("GET", client.path)
    if (current["agent_endpoint"]["version_selector"]["version_selection_rules"] != rules
            or current["versions"]["latest"]["version"] != version):
        raise RuntimeError("Endpoint or latest version changed during ownership handoff")
    select(client, version)
    print(f"Explicitly adopted existing agent at version {version}; stop azd deployments to this agent.")
    return version


def response_text(response: dict) -> str:
    if response.get("object") != "response" or response.get("status") != "completed" or not response.get("id"):
        raise ValueError("Foundry response did not complete successfully")
    return "\n".join(
        content["text"] for item in response.get("output", []) if item.get("type") == "message"
        for content in item.get("content", []) if content.get("type") == "output_text"
    )


def assert_number(text: str, expected: float) -> None:
    value = text.strip()
    if (not re.fullmatch(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", value)
            or not math.isclose(float(value), expected, rel_tol=0.001, abs_tol=0.001)):
        raise ValueError(f"Smoke response does not contain expected numeric result {expected}: {text}")


def smoke(client: Foundry, version: str | None) -> list[dict]:
    body = {} if version is None else {
        "version_indicator": {"type": "version_ref", "agent_version": concrete_version(version)}
    }
    session = client.request("POST", f"{client.path}/endpoint/sessions", body)
    session_id = session["agent_session_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", session_id):
        raise ValueError("Invalid session identifier")
    session_path = f"{client.path}/endpoint/sessions/{session_id}"
    results = []
    try:
        client.wait(session_path)
        for prompt, expected in (
            ("Use rectangle_area for length 3 and width 4. Reply with only the numeric area.", 12.0),
            ("Use circle_area for radius 2. Reply with only the numeric area as a decimal.", 4 * math.pi),
            ("Use solve_linear_equation for a=2 and b=-8. Reply with only the numeric solution.", 4.0),
        ):
            response = client.request("POST", f"{client.path}/endpoint/protocols/openai/responses", {
                "input": prompt, "stream": False, "store": False, "agent_session_id": session_id,
            })
            assert_number(response_text(response), expected)
            results.append({"expected": expected, "response_id": response["id"], "passed": True})
    finally:
        client.request("DELETE", session_path)
    return results


def candidate_smoke(client: Foundry, version: str, new_role: bool) -> list[dict]:
    for attempt in range(5):
        try:
            return smoke(client, version)
        except HTTPError as error:
            if not new_role or error.code not in (401, 403, 500, 502, 503, 504) or attempt == 4:
                raise
            print(
                f"Candidate smoke returned HTTP {error.code} after a new model role assignment; "
                f"retrying in 60 seconds ({attempt + 1}/4).",
                file=sys.stderr, flush=True,
            )
            time.sleep(60)
    raise RuntimeError("Candidate smoke retry limit exhausted")


def definition(image: str) -> dict:
    endpoint = required("AZURE_OPENAI_ENDPOINT")
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".openai.azure.com"):
        raise ValueError("Expected a direct Azure OpenAI resource endpoint")
    return {
        "kind": "hosted", "container_configuration": {"image": image},
        "cpu": "1", "memory": "2Gi",
        "protocol_versions": [{"protocol": "responses", "version": "2.0.0"}],
        "environment_variables": {
            "AZURE_OPENAI_ENDPOINT": endpoint,
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": required("AZURE_AI_MODEL_DEPLOYMENT_NAME"),
            "PYTHONNOUSERSITE": "1",
            "ENABLE_SWAGGER": "false",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false",
        },
    }


def verify_image(version: dict, expected: str) -> None:
    if version["definition"]["container_configuration"]["image"] != expected:
        raise ValueError("Foundry version does not reference the approved immutable image")


def deploy(release: dict, environment: str, output: Path) -> None:
    validate_release(release)
    acr = registry()
    if image_digest(f"math-tutor:{release['tag']}") != release["digest"]:
        raise ValueError("Registry digest does not match release")
    image = f"{acr['loginServer']}/math-tutor@{release['digest']}"
    config = definition(image)
    client = Foundry()
    previous_agent = client.get_agent()
    previous = deployment_previous_version(client, previous_agent) if previous_agent else None
    body = {"definition": config}
    if previous_agent is None:
        created = client.request("POST", "/agents", {"name": client.agent, **body})
        version = concrete_version(created["versions"]["latest"]["version"])
    else:
        created = client.request("POST", f"{client.path}/versions", body)
        version = concrete_version(created["version"])
    record = {
        **release, "environment": environment, "project_endpoint": client.base,
        "agent": client.agent, "version": version, "previous_version": previous,
        "registry_resource_id": acr["id"], "configuration": config,
        "workflow_run_id": required("GITHUB_RUN_ID"), "status": "candidate",
    }
    write_json(output, record)
    active = client.wait(f"{client.path}/versions/{version}")
    verify_image(active, image)
    new_role = grant_model_access(
        required("AZURE_AI_ACCOUNT_ID"), required("AZURE_AI_PROJECT_ID"),
        active["instance_identity"]["principal_id"],
    )
    if previous is None:
        select(client, version)
    record["candidate_smoke"] = candidate_smoke(client, version, new_role)
    if previous is not None and selected_version(client.request("GET", client.path)) != previous:
        raise RuntimeError("Endpoint changed during deployment; refusing promotion")
    try:
        select(client, version)
        record["endpoint_smoke"] = smoke(client, None)
    except (ValueError, RuntimeError, OSError):
        if previous is not None and selected_version(client.request("GET", client.path)) == version:
            select(client, previous)
        raise
    record["status"] = "passed"
    write_json(output, record)


def promote(release: dict, environment: str, output: Path) -> None:
    validate_release(release)
    if environment not in ("test", "prod"):
        raise ValueError("Promotion target must be test or prod")
    source_environment = {"test": "dev", "prod": "test"}[environment]
    if release.get("environment") != source_environment or release.get("status") != "passed":
        raise ValueError("Promotion requires a passing deployment in the preceding environment")
    if release.get("registry_resource_id", "").lower() != required("SOURCE_ACR_RESOURCE_ID").lower():
        raise ValueError("Release registry is not the approved promotion source")
    registry()
    target_registry = required("AZURE_CONTAINER_REGISTRY_NAME")
    repositories = azure("acr", "repository", "list", "--name", target_registry, "--query", "{items:@}")["items"]
    tags = []
    if "math-tutor" in repositories:
        tags = azure(
            "acr", "repository", "show-tags", "--name", target_registry,
            "--repository", "math-tutor", "--query", "{items:@}",
        )["items"]
    if release["tag"] not in tags:
        command(
            "az", "acr", "import", "--name", target_registry,
            "--registry", required("SOURCE_ACR_RESOURCE_ID"),
            "--source", f"math-tutor@{release['digest']}",
            "--image", f"math-tutor:{release['tag']}", "--only-show-errors",
        )
    if image_digest(f"math-tutor:{release['tag']}") != release["digest"]:
        raise ValueError("Imported manifest digest changed")
    lock_image(release["tag"])
    deploy(release, environment, output)


def rollback(record: dict, environment: str, output: Path) -> None:
    validate_release(record)
    client = Foundry()
    if (record.get("environment") != environment or record.get("project_endpoint") != client.base
            or record.get("agent") != client.agent or record.get("status") != "passed"):
        raise ValueError("Rollback record does not match the target environment/agent")
    version = concrete_version(record["version"])
    actual = client.wait(f"{client.path}/versions/{version}")
    if any(actual["definition"].get(key) != value for key, value in record["configuration"].items()):
        raise ValueError("Rollback version differs from the recorded configuration")
    previous = selected_version(client.request("GET", client.path))
    smoke(client, version)
    if selected_version(client.request("GET", client.path)) != previous:
        raise RuntimeError("Endpoint changed during rollback validation")
    select(client, version)
    try:
        results = smoke(client, None)
    except (ValueError, RuntimeError, OSError):
        if selected_version(client.request("GET", client.path)) == version:
            select(client, previous)
        raise
    write_json(output, {**record, "rollback_run_id": required("GITHUB_RUN_ID"), "endpoint_smoke": results})


def fetch_record(run_id: str, environment: str, output: Path) -> None:
    if not run_id.isdigit():
        raise ValueError("Invalid source workflow run ID")
    repo = required("GITHUB_REPOSITORY")
    run = json.loads(command("gh", "api", f"repos/{repo}/actions/runs/{run_id}"))
    expected_workflow = ".github/workflows/release.yml" if environment == "dev" else ".github/workflows/promote.yml"
    if (run["conclusion"] != "success" or run["head_branch"] != "main"
            or run["event"] not in ("push", "workflow_dispatch") or run["path"] != expected_workflow
            or run["repository"]["full_name"] != repo):
        raise ValueError("Source run is not an approved successful deployment workflow")
    command("gh", "run", "download", run_id, "--repo", repo,
            "--name", f"deployment-{environment}", "--dir", str(output.parent))
    record = json.loads(output.read_text(encoding="utf-8"))
    validate_release(record)
    if (str(record.get("workflow_run_id")) != run_id or record.get("environment") != environment
            or record.get("status") != "passed"):
        raise ValueError("Downloaded deployment provenance does not match source run")
    if environment == "dev" and (record["commit"] != run["head_sha"] or str(record["build_run_id"]) != run_id):
        raise ValueError("Dev release does not match the source build commit/run")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("manifest", "deploy", "promote", "rollback", "fetch"))
    parser.add_argument("--environment", choices=ENVIRONMENTS, default="dev")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("release-output/deployment.json"))
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.action == "fetch":
        fetch_record(args.run_id or "", args.environment, args.output)
        return
    if args.action == "manifest":
        registry()
        release = {
            "schema_version": 1, "repository": "math-tutor", "platform": "linux/amd64",
            "digest": required("IMAGE_DIGEST"), "commit": required("GITHUB_SHA"),
            "build_run_id": required("GITHUB_RUN_ID"), "github_repository": required("GITHUB_REPOSITORY"),
            "tag": required("IMAGE_TAG"),
            "evidence": {
                "workflow_run_url": f"https://github.com/{required('GITHUB_REPOSITORY')}/actions/runs/{required('GITHUB_RUN_ID')}",
                "scan_artifact": "release/scan.json",
                "sbom_artifact": "release/sbom.json",
            },
        }
        validate_release(release)
        if image_digest(f"math-tutor:{release['tag']}") != release["digest"]:
            raise ValueError("Published image does not match build output")
        lock_image(release["tag"])
        write_json(args.output, release)
        return
    if args.input is None:
        parser.error("--input is required")
    record = json.loads(args.input.read_text(encoding="utf-8"))
    if args.action == "deploy":
        if args.environment != "dev":
            raise ValueError("Direct deployment is restricted to dev; use promotion")
        deploy(record, args.environment, args.output)
    elif args.action == "promote":
        promote(record, args.environment, args.output)
    else:
        rollback(record, args.environment, args.output)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"Delivery failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
