"""Grant the azd-deployed hosted identity access to its model account."""

import json
from scripts.delivery import command, grant_model_access, required


def main() -> None:
    configuration = json.loads(command(
        "azd", "env", "get-values", "--output", "json",
        "--environment", required("AZURE_ENV_NAME"),
    ))
    if not isinstance(configuration, dict):
        raise ValueError("Expected an azd environment JSON object")
    keys = (
        "AZURE_AI_ACCOUNT_ID", "AZURE_AI_PROJECT_ID",
        "AGENT_MATH_TUTOR_INSTANCE_IDENTITY_PRINCIPAL_ID",
    )
    for key in keys:
        if not isinstance(configuration.get(key), str) or not configuration[key].strip():
            raise ValueError(f"Required azd deployment output is missing: {key}")
    scope, project, principal = (configuration[key].strip() for key in keys)
    grant_model_access(scope, project, principal)


if __name__ == "__main__":
    main()
