"""Opt-in Swagger documentation for the existing hosted Responses routes."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse


_RESPONSE = {
    "description": "Hosted Responses result.",
    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Response"}}},
}
_RESPONSE_ID = {
    "name": "response_id",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
}
OPENAPI_SCHEMA = {
    "openapi": "3.0.3",
    "info": {
        "title": "Math Tutor Hosted Agent",
        "version": "2.0.0",
        "description": (
            "Local documentation for the existing Foundry Responses 2.0.0 server. "
            "This documents common request fields, not every SDK protocol option. "
            "Try it out invokes the configured model and can incur Azure charges. "
            "Use stream=false in Swagger for a normal JSON result."
        ),
    },
    "servers": [{"url": "/"}],
    "paths": {
        "/readiness": {
            "get": {
                "operationId": "readiness",
                "summary": "Check server readiness without model inference",
                "responses": {"200": {"description": "Server is ready; model access is not checked."}},
            },
        },
        "/responses": {
            "post": {
                "operationId": "createResponse",
                "summary": "Send a message to the hosted agent",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/CreateResponse"},
                        "example": {
                            "input": "Find the area of a rectangle 3 cm by 4 cm.",
                            "stream": False,
                            "store": True,
                        },
                    }},
                },
                "responses": {
                    "200": {
                        "description": "JSON response, or server-sent events when stream=true.",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Response"}},
                            "text/event-stream": {"schema": {"type": "string"}},
                        },
                    },
                    "400": {"description": "Invalid request."},
                    "422": {"description": "Request validation failed."},
                    "500": {"description": "Agent or upstream model request failed."},
                },
            },
        },
        "/responses/{response_id}": {
            "get": {
                "operationId": "getResponse",
                "summary": "Retrieve a stored response",
                "parameters": [_RESPONSE_ID],
                "responses": {"200": _RESPONSE, "404": {"description": "Response not found."}},
            },
            "delete": {
                "operationId": "deleteResponse",
                "summary": "Delete a stored response",
                "parameters": [_RESPONSE_ID],
                "responses": {"200": {"description": "Deletion result."}},
            },
        },
        "/responses/{response_id}/cancel": {
            "post": {
                "operationId": "cancelResponse",
                "summary": "Cancel a background response",
                "parameters": [_RESPONSE_ID],
                "responses": {
                    "200": _RESPONSE,
                    "400": {"description": "Response cannot be cancelled."},
                    "404": {"description": "Response not found."},
                },
            },
        },
        "/responses/{response_id}/input_items": {
            "get": {
                "operationId": "getInputItems",
                "summary": "Retrieve input items for a stored response",
                "parameters": [_RESPONSE_ID],
                "responses": {"200": {"description": "Response input items."}},
            },
        },
    },
    "components": {"schemas": {
        "CreateResponse": {
            "type": "object",
            "required": ["input"],
            "properties": {
                "input": {"oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                ]},
                "stream": {"type": "boolean", "default": False},
                "store": {"type": "boolean", "description": "Store the response for later continuation."},
                "background": {"type": "boolean", "description": "Run the response in the background."},
                "previous_response_id": {
                    "type": "string",
                    "description": "ID of an earlier stored response to continue the conversation.",
                },
            },
            "additionalProperties": True,
        },
        "Response": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "object": {"type": "string", "example": "response"},
                "status": {"type": "string"},
                "output": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            },
            "additionalProperties": True,
        },
    }},
}

_SWAGGER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Math Tutor Hosted Agent - Swagger UI</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.34.1/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.34.1/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({
      url: "/openapi.json",
      dom_id: "#swagger-ui",
      validatorUrl: null
    });
  </script>
</body>
</html>
"""


async def _openapi(request: Request) -> JSONResponse:
    return JSONResponse(OPENAPI_SCHEMA)


async def _swagger(request: Request) -> HTMLResponse:
    return HTMLResponse(_SWAGGER_HTML)


def add_swagger_routes(server: Starlette) -> None:
    server.add_route("/openapi.json", _openapi, methods=["GET"], include_in_schema=False)
    server.add_route("/docs", _swagger, methods=["GET"], include_in_schema=False)
