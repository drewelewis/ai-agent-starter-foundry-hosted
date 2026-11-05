# Math tutor development

This project was built with the microsoft-foundry skill. Before working on or
answering questions about Foundry agents, read the microsoft-foundry skill first.
If you are in VS Code, read the vscode-microsoft-foundry skill first.

Keep numerical logic in operations and typed tool wrappers in tools. Register
tools in tools/catalog.py so the hosted agent exposes all supported capabilities.
Preserve the current Agent Framework Agent/AgentSession API. Run `python -m pytest -q` for
offline validation; do not make live model calls without Azure configuration.

The local server and Foundry container start main.py on port 8088 using
ResponsesHostServer and Responses protocol 2.0.0. chat.py is an HTTP client of
that server; it must not create its own agent or model client. Do not add a
separate REST API or Swagger server. ENABLE_SWAGGER may add /docs and
/openapi.json to the same hosted server for local testing; default it to false.
Install requirements-dev.txt for offline testing. Upgrade Agent Framework,
and Foundry hosting packages as a compatible set, not independently.
