"""Reconcile environment infrastructure and export its deployment configuration."""

import argparse
import json
import os
from pathlib import Path

from scripts.delivery import azure, command, required, write_json


CONFIGURATION_KEYS = (
    "AZURE_CONTAINER_REGISTRY_NAME", "AZURE_CONTAINER_REGISTRY_ID",
    "AZURE_AI_ACCOUNT_ID", "AZURE_AI_PROJECT_ID", "AZURE_AI_PROJECT_ENDPOINT",
    "AZURE_OPENAI_ENDPOINT", "AZURE_AI_MODEL_DEPLOYMENT_NAME",
)


def export_configuration(path: Path) -> None:
    outputs = json.loads(path.read_text(encoding="utf-8"))
    values = {}
    for key in CONFIGURATION_KEYS:
        value = outputs.get(key, {}).get("value")
        if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n"):
            raise ValueError(f"Missing or invalid infrastructure output: {key}")
        values[key] = value
    with Path(required("GITHUB_ENV")).open("a", encoding="utf-8") as environment:
        environment.writelines(f"{key}={value}\n" for key, value in values.items())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("dev", "test", "prod"), required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--configure-from", type=Path)
    args = parser.parse_args()
    if args.configure_from is not None:
        if args.apply:
            parser.error("--configure-from cannot be combined with --apply")
        export_configuration(args.configure_from)
        return
    group = required("AZURE_RESOURCE_GROUP")
    location = required("AZURE_LOCATION")
    subscription = required("AZURE_SUBSCRIPTION_ID")
    account = azure("account", "show")
    if account["id"].lower() != subscription.lower():
        raise ValueError("Azure login subscription does not match the target environment")
    if args.apply:
        azure("group", "create", "--name", group, "--location", location)
    else:
        azure("group", "show", "--name", group)
    compiled = azure("bicep", "build-params", "--file", f"infra/environments/{args.environment}.bicepparam", "--stdout")
    parameters = json.loads(compiled["parametersJson"])["parameters"]
    parameters["location"] = {"value": location}
    tags = parameters.get("tags", {"value": {}})["value"]
    parameters["tags"] = {"value": {**tags, "application": "math-tutor", "environment": args.environment}}
    for variable, parameter in (
        ("AZURE_AI_ACCOUNT_NAME", "foundryAccountName"),
        ("AZURE_AI_PROJECT_NAME", "foundryProjectName"),
        ("AZURE_CONTAINER_REGISTRY_NAME", "containerRegistryName"),
    ):
        value = os.environ.get(variable, "").strip()
        if value:
            parameters[parameter] = {"value": value}
    provision_model = os.environ.get("PROVISION_MODEL", "true")
    if provision_model not in ("true", "false"):
        raise ValueError("PROVISION_MODEL must be true or false")
    if provision_model == "true":
        model = {
            "deployModel": True,
            "modelName": os.environ.get("MODEL_NAME") or "gpt-5-mini",
            "modelVersion": os.environ.get("MODEL_VERSION") or "2025-08-07",
            "modelSku": os.environ.get("MODEL_SKU") or "GlobalStandard",
            "modelCapacity": int(os.environ.get("MODEL_CAPACITY") or "100"),
        }
        if model["modelCapacity"] < 1:
            raise ValueError("MODEL_CAPACITY must be positive")
        parameters.update({key: {"value": value} for key, value in model.items()})
    else:
        parameters["deployModel"] = {"value": False}
    path = Path("release-output/infra.parameters.json")
    write_json(path, {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": parameters,
    })
    base = ("--resource-group", group, "--template-file", "infra/main.bicep", "--parameters", f"@{path}")
    azure("deployment", "group", "validate", *base)
    print(command("az", "deployment", "group", "what-if", *base, "--no-pretty-print"))
    if args.apply:
        result = azure("deployment", "group", "create", "--name", "math-tutor-infra", *base)
        write_json(Path("release-output/infrastructure.json"), result["properties"]["outputs"])


if __name__ == "__main__":
    main()
