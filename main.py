"""Foundry hosted-agent entrypoint using the SDK's Responses protocol server."""

import asyncio
import os

from agent_framework_foundry_hosting import ResponsesHostServer
from dotenv import load_dotenv

from agents.tutor_agent import create_tutor_agent, model_configuration
from server_docs import add_swagger_routes


async def main() -> None:
    load_dotenv(override=False)
    model_configuration()
    enable_swagger = os.getenv("ENABLE_SWAGGER", "false").strip().lower()
    if enable_swagger not in ("true", "false"):
        raise ValueError("ENABLE_SWAGGER must be true or false.")
    server = ResponsesHostServer(agent=create_tutor_agent)
    if enable_swagger == "true":
        add_swagger_routes(server)
    await server.run_async(port=int(os.getenv("PORT") or os.getenv("DEFAULT_AD_PORT", "8088")))


if __name__ == "__main__":
    asyncio.run(main())
