"""Offline delivery safety/contract tests; no Azure or GitHub requests."""

import json
from http.client import RemoteDisconnected
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError
from types import SimpleNamespace

import pytest
import yaml

from scripts import azd_runtime, container_smoke, delivery, infrastructure


ROOT = Path(__file__).resolve().parents[1]


def test_command_resolves_windows_cli_launchers(monkeypatch):
    monkeypatch.setattr(delivery.shutil, "which", lambda _: r"C:\tools\az.cmd")
    execute = Mock(return_value=SimpleNamespace(stdout="{}", stderr=""))
    monkeypatch.setattr(delivery.subprocess, "run", execute)
    assert delivery.command("az", "version") == "{}"
    assert execute.call_args.args[0] == (r"C:\tools\az.cmd", "version")
    assert "shell" not in execute.call_args.kwargs


@pytest.fixture
def release(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/math-tutor")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("SOURCE_ACR_RESOURCE_ID", "/subscriptions/source/registries/dev")
    return {
        "schema_version": 1, "repository": "math-tutor", "platform": "linux/amd64",
        "digest": "sha256:" + "a" * 64, "commit": "b" * 40, "build_run_id": "40",
        "github_repository": "example/math-tutor",
        "tag": "sha-" + "b" * 40 + "-run-40-1",
    }


@pytest.fixture
def deployed(release):
    return {
        **release, "environment": "dev", "status": "passed",
        "registry_resource_id": "/subscriptions/source/registries/dev",
        "project_endpoint": "https://example.services.ai.azure.com/api/projects/tutor",
        "agent": "math-tutor", "version": "1", "configuration": {"kind": "hosted"},
        "workflow_run_id": "40",
    }


class FakeFoundry:
    base = "https://example.services.ai.azure.com/api/projects/tutor"
    agent = "math-tutor"
    path = "/agents/math-tutor"

    def __init__(self):
        self.selected = "1"
        self.calls = []
        self.config = {"kind": "hosted"}
        self.agent_exists = True

    def get_agent(self):
        return self.request("GET", self.path) if self.agent_exists else None

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "PATCH":
            self.selected = body["agent_endpoint"]["version_selector"]["version_selection_rules"][0]["agent_version"]
            return {}
        if method == "POST":
            self.config = body["definition"]
            if path == "/agents":
                return {"versions": {"latest": {"version": "2"}}}
            return {"version": "2"}
        return {"agent_endpoint": {"version_selector": delivery.selector(self.selected)}}

    def wait(self, path):
        return {
            "status": "active", "definition": self.config,
            "instance_identity": {"principal_id": "22222222-2222-2222-2222-222222222222"},
        }


@pytest.fixture
def orchestration(monkeypatch, release):
    client = FakeFoundry()
    monkeypatch.setattr(delivery, "Foundry", lambda: client)
    monkeypatch.setattr(delivery, "registry", lambda: {"id": "/target/acr", "loginServer": "target.azurecr.io"})
    monkeypatch.setattr(delivery, "image_digest", lambda image: release["digest"])
    monkeypatch.setattr(delivery, "definition", lambda image: {
        "kind": "hosted", "container_configuration": {"image": image},
    })
    monkeypatch.setattr(delivery, "smoke", Mock(return_value=[{"passed": True}]))
    monkeypatch.setenv("AZURE_AI_ACCOUNT_ID", "/target/account")
    monkeypatch.setenv("AZURE_AI_PROJECT_ID", "/target/account/projects/tutor")
    monkeypatch.setattr(delivery, "grant_model_access", Mock(return_value=False))
    return client


@pytest.mark.parametrize(("key", "value"), [
    ("digest", "latest"), ("digest", "sha256:" + "A" * 64),
    ("repository", "untrusted"), ("platform", "linux/arm64"),
    ("commit", "main"), ("tag", "latest"),
    ("github_repository", "other/repo"), ("build_run_id", "x"),
])
def test_release_validation_rejects_bad_inputs(release, key, value):
    release[key] = value
    with pytest.raises(ValueError):
        delivery.validate_release(release)


@pytest.mark.parametrize("version", ["latest", "@latest", "draft-1", "0", "1/../../agents", 1])
def test_only_concrete_versions(version):
    with pytest.raises(ValueError):
        delivery.concrete_version(version)


@pytest.mark.parametrize("text", ["12", " 12.000 ", "1.2e1"])
def test_numeric_smoke_accepts_numeric_answer(text):
    delivery.assert_number(text, 12)


@pytest.mark.parametrize("text", ["3 times 4 is not 12", "NaN", "inf", "11", "", "12 and 13"])
def test_numeric_smoke_rejects_wrong_or_ambiguous_answers(text):
    with pytest.raises(ValueError):
        delivery.assert_number(text, 12)


def test_rounding_tolerance():
    delivery.assert_number("12.566", 4 * 3.141592653589793)


def test_container_check_retries_cold_start_disconnect(monkeypatch):
    ready = Mock()
    ready.__enter__ = Mock(return_value=Mock(status=200))
    ready.__exit__ = Mock(return_value=False)
    malformed = HTTPError("http://local/responses", 400, "invalid JSON", {}, None)
    malformed.read = Mock(return_value=b'{"detail":"invalid JSON"}')
    open_url = Mock(side_effect=[RemoteDisconnected("starting"), ready, malformed])
    monkeypatch.setattr(container_smoke, "urlopen", open_url)
    monkeypatch.setattr(container_smoke.time, "sleep", Mock())
    container_smoke.main()
    assert open_url.call_count == 3


def test_candidate_test_precedes_endpoint_switch(release, orchestration, tmp_path):
    client = orchestration
    tested_versions = []

    def smoke(_, version):
        tested_versions.append((version, client.selected))
        return [{"passed": True}]

    delivery.smoke.side_effect = smoke
    output = tmp_path / "deployment.json"
    delivery.deploy(release, "dev", output)
    assert tested_versions == [("2", "1"), (None, "2")]
    record = json.loads(output.read_text())
    assert record["previous_version"] == "1"
    assert record["version"] == "2"
    assert record["status"] == "passed"
    assert record["configuration"]["container_configuration"]["image"].endswith("@" + release["digest"])


def test_first_deployment_records_and_pins_new_version(release, orchestration, tmp_path):
    orchestration.agent_exists = False
    delivery.deploy(release, "test", tmp_path / "deployment.json")
    assert orchestration.selected == "2"
    assert any(method == "POST" and path == "/agents" for method, path, _ in orchestration.calls)


def test_failed_first_smoke_leaves_concrete_bootstrap_pin(release, orchestration, tmp_path):
    orchestration.agent_exists = False
    delivery.smoke.side_effect = ValueError("model permission missing")
    with pytest.raises(ValueError, match="model permission"):
        delivery.deploy(release, "dev", tmp_path / "record.json")
    assert orchestration.selected == "2"


def test_failed_candidate_never_changes_endpoint(release, orchestration, tmp_path):
    delivery.smoke.side_effect = ValueError("candidate failed")
    output = tmp_path / "deployment.json"
    with pytest.raises(ValueError, match="candidate failed"):
        delivery.deploy(release, "dev", output)
    assert orchestration.selected == "1"
    assert json.loads(output.read_text())["status"] == "candidate"
    assert not any(method == "PATCH" for method, _, _ in orchestration.calls)


def test_runtime_access_precedes_live_smoke(release, orchestration, tmp_path):
    def smoke(*args):
        delivery.grant_model_access.assert_called_once_with(
            "/target/account", "/target/account/projects/tutor",
            "22222222-2222-2222-2222-222222222222",
        )
        return []

    delivery.smoke.side_effect = smoke
    delivery.deploy(release, "dev", tmp_path / "record.json")


def test_runtime_permission_failure_preserves_endpoint(release, orchestration, tmp_path):
    delivery.grant_model_access.side_effect = PermissionError("role assignment forbidden")
    with pytest.raises(PermissionError, match="forbidden"):
        delivery.deploy(release, "dev", tmp_path / "record.json")
    delivery.smoke.assert_not_called()
    assert orchestration.selected == "1"


def test_explicit_azd_handoff_pins_latest_before_creating_candidate(monkeypatch, release, orchestration, tmp_path):
    client = orchestration
    request = client.request
    client.selected = "@latest"
    latest = "1"

    def wrapped(method, path, body=None):
        nonlocal latest
        if method == "GET" and path == client.path:
            rules = [{"type": "FixedRatio", "agent_version": client.selected, "traffic_percentage": 100}]
            return {
                "agent_endpoint": {"version_selector": {"version_selection_rules": rules}},
                "versions": {"latest": {"version": latest}},
            }
        if method == "POST":
            assert client.selected == "1"
            latest = "2"
        return request(method, path, body)

    monkeypatch.setattr(client, "request", wrapped)
    monkeypatch.setenv("ADOPT_EXISTING_VERSION", "1")
    delivery.deploy(release, "dev", tmp_path / "record.json")
    assert client.selected == "2"
    assert json.loads((tmp_path / "record.json").read_text())["previous_version"] == "1"


@pytest.mark.parametrize("configured", [None, "2", "@latest"])
def test_azd_handoff_rejects_missing_or_wrong_version(monkeypatch, orchestration, configured):
    if configured is None:
        monkeypatch.delenv("ADOPT_EXISTING_VERSION", raising=False)
    else:
        monkeypatch.setenv("ADOPT_EXISTING_VERSION", configured)
    agent = {
        "agent_endpoint": {"version_selector": {"version_selection_rules": [
            {"type": "FixedRatio", "agent_version": "@latest", "traffic_percentage": 100},
        ]}},
        "versions": {"latest": {"version": "1"}},
    }
    with pytest.raises(ValueError):
        delivery.deployment_previous_version(orchestration, agent)
    assert not orchestration.calls


def test_azd_handoff_rejects_concurrent_changes(monkeypatch, orchestration):
    monkeypatch.setenv("ADOPT_EXISTING_VERSION", "1")
    agent = {
        "agent_endpoint": {"version_selector": {"version_selection_rules": [
            {"type": "FixedRatio", "agent_version": "@latest", "traffic_percentage": 100},
        ]}},
        "versions": {"latest": {"version": "1"}},
    }
    with pytest.raises(RuntimeError, match="changed during ownership handoff"):
        delivery.deployment_previous_version(orchestration, agent)
    assert not any(method == "PATCH" for method, _, _ in orchestration.calls)


def test_new_role_retries_transient_smoke_in_fresh_sessions(monkeypatch):
    smoke = Mock(side_effect=[
        HTTPError("https://foundry/responses", 500, "upstream unauthorized", {}, None),
        HTTPError("https://foundry/responses", 403, "propagating", {}, None),
        [{"passed": True}],
    ])
    monkeypatch.setattr(delivery, "smoke", smoke)
    sleep = Mock()
    monkeypatch.setattr(delivery.time, "sleep", sleep)
    assert delivery.candidate_smoke(Mock(), "2", True) == [{"passed": True}]
    assert smoke.call_count == 3
    assert sleep.call_args_list == [((60,),), ((60,),)]


@pytest.mark.parametrize(("new_role", "error", "attempts"), [
    (True, HTTPError("https://foundry", 401, "unauthorized", {}, None), 5),
    (False, HTTPError("https://foundry", 500, "failed", {}, None), 1),
    (True, HTTPError("https://foundry", 400, "bad request", {}, None), 1),
    (True, ValueError("wrong numeric result"), 1),
])
def test_candidate_retries_are_bounded_and_fail_closed(monkeypatch, new_role, error, attempts):
    smoke = Mock(side_effect=error)
    monkeypatch.setattr(delivery, "smoke", smoke)
    monkeypatch.setattr(delivery.time, "sleep", Mock())
    with pytest.raises(type(error)):
        delivery.candidate_smoke(Mock(), "2", new_role)
    assert smoke.call_count == attempts


def test_endpoint_smoke_failure_restores_previous_version(release, orchestration, tmp_path):
    delivery.smoke.side_effect = [[{"passed": True}], ValueError("endpoint failed")]
    with pytest.raises(ValueError, match="endpoint failed"):
        delivery.deploy(release, "dev", tmp_path / "deployment.json")
    assert orchestration.selected == "1"


def test_concurrent_endpoint_writer_aborts_promotion(release, orchestration, tmp_path):
    def smoke(*args):
        orchestration.selected = "3"
        return []

    delivery.smoke.side_effect = smoke
    with pytest.raises(RuntimeError, match="Endpoint changed"):
        delivery.deploy(release, "dev", tmp_path / "deployment.json")
    assert orchestration.selected == "3"


def test_wrong_registry_digest_aborts_before_foundry(release, orchestration, monkeypatch, tmp_path):
    monkeypatch.setattr(delivery, "image_digest", lambda _: "sha256:" + "c" * 64)
    with pytest.raises(ValueError, match="digest"):
        delivery.deploy(release, "dev", tmp_path / "deployment.json")
    assert orchestration.calls == []


@pytest.mark.parametrize(("environment", "status"), [("prod", "passed"), ("dev", "candidate"), ("test", "passed")])
def test_promotion_cannot_skip_preceding_environment(deployed, environment, status, tmp_path):
    deployed.update(environment=environment, status=status)
    with pytest.raises(ValueError, match="preceding environment"):
        delivery.promote(deployed, "test", tmp_path / "record.json")


def test_import_uses_digest_and_verifies_it(deployed, orchestration, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(delivery, "command", lambda *args: calls.append(args) or "")
    monkeypatch.setattr(delivery, "lock_image", lambda _: None)
    monkeypatch.setattr(delivery, "azure", lambda *args: {"items": []})
    monkeypatch.setenv("AZURE_CONTAINER_REGISTRY_NAME", "target")
    delivery.promote(deployed, "test", tmp_path / "record.json")
    assert calls[0][0:3] == ("az", "acr", "import")
    assert f"math-tutor@{deployed['digest']}" in calls[0]
    assert "--force" not in calls[0]
    assert not any("build" in call for call in calls)


def test_promotion_retry_reuses_existing_matching_image(deployed, orchestration, monkeypatch, tmp_path):
    execute = Mock()
    monkeypatch.setattr(delivery, "command", execute)
    monkeypatch.setattr(delivery, "azure", lambda *args: {"items": [deployed["tag"]] if "show-tags" in args else ["math-tutor"]})
    monkeypatch.setattr(delivery, "lock_image", lambda _: None)
    monkeypatch.setenv("AZURE_CONTAINER_REGISTRY_NAME", "target")
    delivery.promote(deployed, "test", tmp_path / "record.json")
    execute.assert_not_called()


def test_existing_promotion_tag_cannot_be_overwritten(deployed, orchestration, monkeypatch, tmp_path):
    execute = Mock()
    monkeypatch.setattr(delivery, "command", execute)
    monkeypatch.setattr(delivery, "azure", lambda *args: {"items": [deployed["tag"]] if "show-tags" in args else ["math-tutor"]})
    monkeypatch.setattr(delivery, "image_digest", lambda _: "sha256:" + "c" * 64)
    monkeypatch.setenv("AZURE_CONTAINER_REGISTRY_NAME", "target")
    with pytest.raises(ValueError, match="digest changed"):
        delivery.promote(deployed, "test", tmp_path / "record.json")
    execute.assert_not_called()


def test_promotion_rejects_unapproved_registry(deployed, monkeypatch, tmp_path):
    monkeypatch.setenv("SOURCE_ACR_RESOURCE_ID", "/other/acr")
    with pytest.raises(ValueError, match="approved promotion source"):
        delivery.promote(deployed, "test", tmp_path / "record.json")


def test_rollback_restores_recorded_version(deployed, orchestration, tmp_path):
    orchestration.selected = "2"
    delivery.rollback(deployed, "dev", tmp_path / "record.json")
    assert orchestration.selected == "1"


def test_rollback_smoke_failure_restores_original_selection(deployed, orchestration, tmp_path):
    orchestration.selected = "2"
    delivery.smoke.side_effect = [[], ValueError("endpoint failed")]
    with pytest.raises(ValueError):
        delivery.rollback(deployed, "dev", tmp_path / "record.json")
    assert orchestration.selected == "2"


def test_rollback_rejects_other_environment(deployed, orchestration, tmp_path):
    with pytest.raises(ValueError, match="target environment"):
        delivery.rollback(deployed, "prod", tmp_path / "record.json")
    assert not orchestration.calls


@pytest.mark.parametrize("url", [
    "http://example.services.ai.azure.com/api/projects/tutor",
    "https://evil.example/api/projects/tutor",
    "https://example.services.ai.azure.com.evil.example/api/projects/tutor",
    "https://example.services.ai.azure.com/api/projects/tutor?redirect=evil",
])
def test_credentials_not_sent_to_untrusted_endpoint(monkeypatch, url):
    monkeypatch.setenv("AZURE_AI_PROJECT_ENDPOINT", url)
    lookup = Mock()
    monkeypatch.setattr(delivery, "azure", lookup)
    with pytest.raises(ValueError):
        delivery.Foundry()
    lookup.assert_not_called()


def test_failed_response_is_not_a_success():
    with pytest.raises(ValueError, match="complete successfully"):
        delivery.response_text({"object": "response", "id": "r", "status": "failed", "output": []})


def test_source_workflow_provenance_is_verified_before_download(monkeypatch, deployed, tmp_path):
    monkeypatch.setattr(delivery, "command", Mock(return_value=json.dumps({
        "conclusion": "success", "head_branch": "feature", "event": "pull_request",
        "path": ".github/workflows/release.yml", "repository": {"full_name": "example/math-tutor"},
    })))
    with pytest.raises(ValueError, match="approved successful"):
        delivery.fetch_record("40", "dev", tmp_path / "deployment.json")
    assert delivery.command.call_count == 1


def test_source_record_matches_github_commit_and_run(monkeypatch, deployed, tmp_path):
    source = {
        "conclusion": "success", "head_branch": "main", "head_sha": deployed["commit"],
        "event": "push", "path": ".github/workflows/release.yml",
        "repository": {"full_name": "example/math-tutor"},
    }

    def command(*args):
        if args[:2] == ("gh", "api"):
            return json.dumps(source)
        (tmp_path / "deployment.json").write_text(json.dumps(deployed))
        return ""

    monkeypatch.setattr(delivery, "command", command)
    delivery.fetch_record("40", "dev", tmp_path / "deployment.json")
    source["head_sha"] = "c" * 40
    with pytest.raises(ValueError, match="source build commit"):
        delivery.fetch_record("40", "dev", tmp_path / "deployment.json")


def test_rollback_rejects_configuration_drift(deployed, orchestration, tmp_path):
    orchestration.config = {"kind": "prompt"}
    with pytest.raises(ValueError, match="recorded configuration"):
        delivery.rollback(deployed, "dev", tmp_path / "record.json")
    assert not any(method == "PATCH" for method, _, _ in orchestration.calls)


def test_candidate_image_is_verified(release, orchestration, tmp_path):
    orchestration.wait = lambda _: {"definition": {"container_configuration": {"image": "wrong"}}}
    with pytest.raises(ValueError, match="approved immutable image"):
        delivery.deploy(release, "dev", tmp_path / "record.json")
    delivery.smoke.assert_not_called()
    assert orchestration.selected == "1"


def test_cli_blocks_direct_prod_deploy(monkeypatch, release, tmp_path):
    path = tmp_path / "release.json"
    path.write_text(json.dumps(release))
    monkeypatch.setattr("sys.argv", [
        "delivery", "deploy", "--environment", "prod", "--input", str(path),
    ])
    with pytest.raises(ValueError, match="restricted to dev"):
        delivery.main()


def test_infra_plan_uses_environment_parameters_without_applying(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "AZURE_RESOURCE_GROUP": "rg-tutor", "AZURE_LOCATION": "northcentralus",
        "AZURE_SUBSCRIPTION_ID": "subscription", "PROVISION_MODEL": "false",
    }.items():
        monkeypatch.setenv(key, value)
    calls = []

    def azure(*args):
        calls.append(args)
        if args == ("account", "show"):
            return {"id": "subscription"}
        if args[:2] == ("bicep", "build-params"):
            return {"parametersJson": json.dumps({"parameters": {
                "containerRegistryName": {"value": "customregistry"},
            }})}
        return {}

    monkeypatch.setattr(infrastructure, "azure", azure)
    monkeypatch.setattr(infrastructure, "command", Mock(return_value="what-if output"))
    monkeypatch.setattr("sys.argv", ["infrastructure", "--environment", "test"])
    infrastructure.main()
    assert not any("create" in args for args in calls)
    parameters = json.loads((tmp_path / "release-output/infra.parameters.json").read_text())["parameters"]
    assert parameters["containerRegistryName"]["value"] == "customregistry"
    assert parameters["tags"]["value"]["environment"] == "test"
    assert parameters["location"]["value"] == "northcentralus"


def test_infra_apply_reconciles_group_and_model_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "AZURE_RESOURCE_GROUP": "rg-tutor", "AZURE_LOCATION": "northcentralus",
        "AZURE_SUBSCRIPTION_ID": "subscription", "AZURE_AI_ACCOUNT_NAME": "adopted-foundry",
    }.items():
        monkeypatch.setenv(key, value)
    for key in ("PROVISION_MODEL", "MODEL_NAME", "MODEL_VERSION", "MODEL_SKU", "MODEL_CAPACITY",
                "AZURE_AI_MODEL_DEPLOYMENT_NAME"):
        monkeypatch.delenv(key, raising=False)
    calls = []

    def azure(*args):
        calls.append(args)
        if args == ("account", "show"):
            return {"id": "subscription"}
        if args[:2] == ("bicep", "build-params"):
            return {"parametersJson": json.dumps({"parameters": {}})}
        if args[:3] == ("deployment", "group", "create"):
            return {"properties": {"outputs": {"example": {"value": "output"}}}}
        return {}

    monkeypatch.setattr(infrastructure, "azure", azure)
    monkeypatch.setattr(infrastructure, "command", Mock(return_value="what-if output"))
    monkeypatch.setattr("sys.argv", ["infrastructure", "--environment", "dev", "--apply"])
    infrastructure.main()
    assert calls[1] == ("group", "create", "--name", "rg-tutor", "--location", "northcentralus")
    parameters = json.loads((tmp_path / "release-output/infra.parameters.json").read_text())["parameters"]
    assert {key: parameters[key]["value"] for key in (
        "deployModel", "modelDeploymentName", "modelName", "modelVersion", "modelSku", "modelCapacity",
        "foundryAccountName",
    )} == {
        "deployModel": True, "modelDeploymentName": "math-tutor", "modelName": "gpt-5-mini",
        "modelVersion": "2025-08-07", "modelSku": "GlobalStandard", "modelCapacity": 1,
        "foundryAccountName": "adopted-foundry",
    }
    assert json.loads((tmp_path / "release-output/infrastructure.json").read_text()) == {
        "example": {"value": "output"},
    }


def test_infra_outputs_configure_downstream_jobs_without_azure(monkeypatch, tmp_path):
    path = tmp_path / "infrastructure.json"
    outputs = {key: {"value": f"configured-{key}"} for key in infrastructure.CONFIGURATION_KEYS}
    path.write_text(json.dumps({**outputs, "UNEXPECTED": {"value": "not-exported"}}))
    environment = tmp_path / "github-env"
    monkeypatch.setenv("GITHUB_ENV", str(environment))
    monkeypatch.setattr("sys.argv", [
        "infrastructure", "--environment", "dev", "--configure-from", str(path),
    ])
    azure = Mock()
    monkeypatch.setattr(infrastructure, "azure", azure)
    infrastructure.main()
    assert environment.read_text().splitlines() == [
        f"{key}=configured-{key}" for key in infrastructure.CONFIGURATION_KEYS
    ]
    azure.assert_not_called()


@pytest.mark.parametrize("value", [None, "", "valid\nINJECTED=true", "valid\rINJECTED=true"])
def test_infra_output_export_rejects_missing_or_multiline_values(monkeypatch, tmp_path, value):
    path = tmp_path / "infrastructure.json"
    outputs = {key: {"value": "configured"} for key in infrastructure.CONFIGURATION_KEYS}
    outputs["AZURE_AI_PROJECT_ID"] = {"value": value}
    path.write_text(json.dumps(outputs))
    environment = tmp_path / "github-env"
    monkeypatch.setenv("GITHUB_ENV", str(environment))
    with pytest.raises(ValueError, match="AZURE_AI_PROJECT_ID"):
        infrastructure.export_configuration(path)
    assert not environment.exists()


def test_azd_hosted_deployment_contract():
    project = yaml.safe_load((ROOT / "azure.yaml").read_text())
    assert project["infra"] == {"provider": "bicep", "path": "infra/azd"}
    assert project["hooks"]["postdeploy"] == {
        "windows": {"shell": "pwsh", "run": "python -m scripts.azd_runtime"},
        "posix": {"shell": "sh", "run": "python3 -m scripts.azd_runtime"},
    }
    assert set(project["services"]) == {"math-tutor"}
    service = project["services"]["math-tutor"]
    assert service["host"] == "azure.ai.agent"
    assert service["kind"] == "hosted"
    assert service["name"] == "math-tutor"
    assert service["language"] == "docker"
    assert service["project"] == "."
    assert "codeConfiguration" not in service
    assert service["docker"] == {
        "path": "dockerfile", "context": ".", "platform": "linux/amd64",
        "remoteBuild": True,
    }
    assert (ROOT / service["docker"]["path"]).is_file()
    dockerfile = (ROOT / service["docker"]["path"]).read_text()
    assert "--mount=" not in dockerfile
    assert "RUN pip install --no-cache-dir -r requirements.txt" in dockerfile
    assert service["container"]["resources"] == {"cpu": "1", "memory": "2Gi"}
    assert service["protocols"] == [{"protocol": "responses", "version": "2.0.0"}]
    assert service["env"] == {
        "AZURE_OPENAI_ENDPOINT": "${AZURE_OPENAI_ENDPOINT}",
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": "${AZURE_AI_MODEL_DEPLOYMENT_NAME}",
        "PYTHONNOUSERSITE": "1",
        "ENABLE_SWAGGER": "false",
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false",
    }
    template = (ROOT / "infra/azd/main.bicep").read_text()
    assert "deployContainerRegistry: true" in template
    for output in (
        "FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ID", "AZURE_TENANT_ID",
        "AZURE_CONTAINER_REGISTRY_NAME", "AZURE_CONTAINER_REGISTRY_ENDPOINT",
        "AZURE_CONTAINER_REGISTRY_RESOURCE_ID", "AZURE_AI_PROJECT_ACR_CONNECTION_NAME",
    ):
        assert f"output {output} string =" in template


@pytest.fixture
def azd_configuration(monkeypatch):
    subscription = "11111111-1111-1111-1111-111111111111"
    scope = f"/subscriptions/{subscription}/resourceGroups/dev/providers/Microsoft.CognitiveServices/accounts/tutor"
    configuration = {
        "AZURE_AI_ACCOUNT_ID": scope,
        "AZURE_AI_PROJECT_ID": f"{scope}/projects/tutor",
        "AGENT_MATH_TUTOR_INSTANCE_IDENTITY_PRINCIPAL_ID": "22222222-2222-2222-2222-222222222222",
    }
    monkeypatch.setenv("AZURE_ENV_NAME", "selected-dev")
    execute = Mock(side_effect=lambda *args: json.dumps(configuration))
    monkeypatch.setattr(azd_runtime, "command", execute)
    return configuration, execute


def test_azd_grants_runtime_model_access(monkeypatch, azd_configuration):
    configuration, execute = azd_configuration
    azure = Mock(side_effect=[{"assignments": []}, {}])
    monkeypatch.setattr(delivery, "azure", azure)
    azd_runtime.main()
    execute.assert_called_once_with(
        "azd", "env", "get-values", "--output", "json", "--environment", "selected-dev",
    )
    assert azure.call_args.args == (
        "role", "assignment", "create", "--assignee-object-id",
        configuration["AGENT_MATH_TUTOR_INSTANCE_IDENTITY_PRINCIPAL_ID"],
        "--assignee-principal-type", "ServicePrincipal", "--role", delivery.MODEL_USER_ROLE,
        "--scope", configuration["AZURE_AI_ACCOUNT_ID"],
        "--subscription", "11111111-1111-1111-1111-111111111111",
    )


def test_azd_runtime_role_is_idempotent(monkeypatch, azd_configuration):
    configuration, _ = azd_configuration
    azure = Mock(return_value={"assignments": [{
        "principalId": configuration["AGENT_MATH_TUTOR_INSTANCE_IDENTITY_PRINCIPAL_ID"],
        "roleDefinitionId": f"/roleDefinitions/{delivery.MODEL_USER_ROLE}",
        "scope": configuration["AZURE_AI_ACCOUNT_ID"],
    }]})
    monkeypatch.setattr(delivery, "azure", azure)
    azd_runtime.main()
    azure.assert_called_once()
    assert azure.call_args.args[:3] == ("role", "assignment", "list")


@pytest.mark.parametrize("key", [
    "AZURE_AI_ACCOUNT_ID", "AZURE_AI_PROJECT_ID",
    "AGENT_MATH_TUTOR_INSTANCE_IDENTITY_PRINCIPAL_ID",
])
def test_azd_runtime_rejects_missing_outputs(monkeypatch, azd_configuration, key):
    configuration, _ = azd_configuration
    del configuration[key]
    azure = Mock()
    monkeypatch.setattr(delivery, "azure", azure)
    with pytest.raises(ValueError, match=key):
        azd_runtime.main()
    azure.assert_not_called()


def test_azd_runtime_rejects_mismatched_account(monkeypatch, azd_configuration):
    configuration, _ = azd_configuration
    configuration["AZURE_AI_PROJECT_ID"] = configuration["AZURE_AI_PROJECT_ID"].replace(
        "/accounts/tutor/", "/accounts/other/",
    )
    azure = Mock()
    monkeypatch.setattr(delivery, "azure", azure)
    with pytest.raises(ValueError, match="same Foundry account"):
        azd_runtime.main()
    azure.assert_not_called()


def test_workflow_safety_contracts():
    workflows = list((ROOT / ".github/workflows").glob("*.yml"))
    assert len(workflows) == 6
    for path in workflows:
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        assert "pull_request_target" not in workflow["on"]
        assert workflow["permissions"] == {"contents": "read"}
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if "uses" in step and not step["uses"].startswith("./"):
                    assert re_full_action_pin(step["uses"]), step["uses"]
                assert "${{ inputs." not in step.get("run", "")
            if job.get("permissions", {}).get("id-token") == "write":
                assert "environment" in job or "uses" in job
    promote = (ROOT / ".github/workflows/promote.yml").read_text()
    assert "docker/build-push-action" not in promote
    reusable = (ROOT / ".github/workflows/deploy.yml").read_text()
    assert "cancel-in-progress: false" in reusable
    assert "PRODUCTION_DEPLOYMENTS_ENABLED" in reusable
    assert "azure/login@" in reusable


def test_release_wires_infrastructure_before_build_and_deployment():
    release = yaml.load((ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader)
    jobs = release["jobs"]
    assert jobs["infrastructure-dev"]["needs"] == "checks"
    assert jobs["infrastructure-dev"]["uses"] == "./.github/workflows/infrastructure.yml"
    assert jobs["infrastructure-dev"]["with"] == {"environment": "dev", "operation": "apply"}
    assert jobs["build"]["needs"] == "infrastructure-dev"
    assert jobs["deploy-dev"]["needs"] == "build"
    assert any(step.get("with", {}).get("name") == "infrastructure-dev" for step in jobs["build"]["steps"])
    assert any("--configure-from infrastructure-input/infrastructure.json" in step.get("run", "")
               for step in jobs["build"]["steps"])
    deploy = yaml.load((ROOT / ".github/workflows/deploy.yml").read_text(), Loader=yaml.BaseLoader)
    configure = [step for step in deploy["jobs"]["deploy"]["steps"]
                 if "--configure-from" in step.get("run", "")]
    assert len(configure) == 1
    assert configure[0]["if"] == "inputs.target_environment == 'dev'"
    infra = yaml.load((ROOT / ".github/workflows/infrastructure.yml").read_text(), Loader=yaml.BaseLoader)
    assert "workflow_call" in infra["on"]
    assert infra["jobs"]["infrastructure"]["env"]["PROVISION_MODEL"] == "${{ vars.PROVISION_MODEL || 'true' }}"
    assert "infra/azd/main.bicep" in (ROOT / ".github/workflows/ci.yml").read_text()
    rollback = yaml.load((ROOT / ".github/workflows/rollback.yml").read_text(), Loader=yaml.BaseLoader)
    restore = [step for step in rollback["jobs"]["rollback"]["steps"]
               if "--configure-from" in step.get("run", "")]
    assert len(restore) == 1
    assert restore[0]["if"] == "inputs.environment == 'dev'"
    assert '--name infrastructure-dev' in restore[0]["run"]


def re_full_action_pin(value):
    import re

    return re.fullmatch(r"[A-Za-z0-9_./-]+@[0-9a-f]{40}", value) is not None
