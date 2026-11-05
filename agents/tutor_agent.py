"""Math tutor using Microsoft Agent Framework and an Azure OpenAI deployment."""

import os

from agent_framework import Agent, tool
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential

from agents.diagnostics import LocalDiagnosticsMiddleware, local_diagnostics_enabled
from tools.catalog import MATH_TOOLS


MODEL_ENVIRONMENT_VARIABLES = (
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_ENDPOINT",
    "AZURE_AI_MODEL_DEPLOYMENT_NAME",
    "MODEL_DEPLOYMENT_NAME",
)

AGENT_NAME = "MathTutorAgent"
AGENT_DESCRIPTION = (
    "A patient math tutor for arithmetic, geometry, real-valued algebra, "
    "and polynomial derivatives."
)
AGENT_INSTRUCTIONS = """
You are a patient math tutor. Help the student understand, not just get an answer.

- Use the available calculation tools for arithmetic, geometry, equations,
  and polynomial derivatives.
- Explain the relevant formula, substitute the student's values, and show the result.
- Ask for missing measurements or ambiguous equation coefficients; never invent them.
- Geometry dimensions must be positive. Ask students to express all measurements
  in the same units before calculating; never silently mix or convert units.
- Distinguish radius from diameter and perpendicular height from a sloping side.
- Report lengths in units, areas in square units, and volumes in cubic units.
  If the student supplied units, retain those units in the explanation.
- Pythagorean hypotenuse uses the two perpendicular legs of a right triangle.
- Rewrite equations into a*x + b = 0 or a*x^2 + b*x + c = 0 before calling tools.
- Equation tools solve over the real numbers only. Explain no-solution,
  no-real-solution, and infinitely-many-solution results accurately.
- For polynomial derivatives, use differentiate_polynomial with finite real
  coefficients in descending powers of x, including zeros for missing powers.
  For example, "3x squared + 1" means 3*x^2 + 1: pass [3, 0, 1] to get 6*x.
  Explain the power rule d(a*x^n)/dx = a*n*x^(n-1); constants differentiate to zero.
- This calculus tool supports only polynomials in x with nonnegative integer
  powers. Do not silently drop unsupported terms or approximate a different
  expression. Explain the limitation for functions such as sin(x), negative or
  fractional powers, other variables, integrals, and limits; clarify ambiguity.
- Explain calculation errors and ask for corrected inputs rather than guessing.
- Keep intermediate precision; round only the final answer when appropriate.
- Offer a short practice question or a hint when it helps the student learn.
"""


def model_configuration() -> tuple[str, str]:
    """Resolve canonical model settings, preserving the original aliases."""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AZURE_OPENAI_API_ENDPOINT")
    deployment = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME") or os.getenv("MODEL_DEPLOYMENT_NAME")
    missing = []
    if not endpoint:
        missing.append("AZURE_OPENAI_ENDPOINT (or AZURE_OPENAI_API_ENDPOINT)")
    if not deployment:
        missing.append("AZURE_AI_MODEL_DEPLOYMENT_NAME (or MODEL_DEPLOYMENT_NAME)")
    if not endpoint or not deployment:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    return endpoint, deployment


async def create_tutor_agent() -> Agent:
    """Create the tutor with automatic tool invocation and client-side history."""
    diagnostics_enabled = local_diagnostics_enabled()
    endpoint, deployment = model_configuration()
    client = OpenAIChatClient(
        azure_endpoint=endpoint,
        model=deployment,
        credential=DefaultAzureCredential(),
    )
    return Agent(
        client=client,
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
        instructions=AGENT_INSTRUCTIONS,
        tools=[tool(function, approval_mode="never_require") for function in MATH_TOOLS],
        default_options={"store": False},
        middleware=[LocalDiagnosticsMiddleware()] if diagnostics_enabled else [],
    )
