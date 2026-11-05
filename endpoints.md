# Hosted agent endpoints

The application has **one server**: [main.py](main.py), running Microsoft's
`ResponsesHostServer` with Responses protocol **2.0.0**. Local development and
the Foundry container use the same protocol.

Default local base URL: **http://localhost:8088**

```powershell
python main.py
```

`PORT` takes precedence over `DEFAULT_AD_PORT`; the default is 8088. Configure
the Azure model using the [getting-started guide](README.md#getting-started).
The local [chat.py](chat.py) client calls these same endpoints.

Examples below use synthetic IDs and abbreviated responses, not complete SDK
schemas. Replace sample IDs with values returned by your server. Actual text,
timestamps, output items, token counts, and optional fields vary.

These are trusted-local-development examples, not the authenticated Foundry
cloud gateway URLs. Do not expose the local server to untrusted clients.
Sending a question invokes the configured Azure model and can incur charges.

## Endpoint summary

| Method | Path | Purpose |
|---|---|---|
| GET | `/readiness` | Check server readiness without model inference |
| POST | `/responses` | Create a JSON or streaming agent response |
| GET | `/responses/{response_id}` | Retrieve a stored response |
| GET | `/responses/{response_id}/input_items` | List a response's input items |
| POST | `/responses/{response_id}/cancel` | Cancel a background response |
| DELETE | `/responses/{response_id}` | Delete a stored response |
| GET | `/docs` | Swagger UI, only when `ENABLE_SWAGGER=true` |
| GET | `/openapi.json` | OpenAPI document, only when `ENABLE_SWAGGER=true` |

There are no separate `/chat`, `/calculate`, `/health`, or `/agent/status`
application endpoints. Calculations are tools invoked through the agent.

## 1. GET /readiness

No request body.

```powershell
Invoke-RestMethod http://localhost:8088/readiness
```

Example response: **200 OK**

```json
{
  "status": "healthy"
}
```

This confirms server readiness, not Azure model access, RBAC, quota, or tool
execution. Send an actual question to verify the complete path.

## 2. POST /responses

Content type: `application/json`.

### Single-turn request

```json
{
  "input": "Find the area of a rectangle 3 cm by 4 cm.",
  "stream": false,
  "store": true
}
```

| Field | Meaning |
|---|---|
| `input` | User text, or an array of protocol input items |
| `stream` | `false` for JSON; `true` for server-sent events (SSE) |
| `store` | Keep the response for retrieval and continuation; use `true` for the lifecycle examples |
| `previous_response_id` | Continue from an earlier stored response |
| `background` | Run asynchronously; `true` requires `store: true` |

The server already has its model deployment and tools configured. You do not
need to send the Azure resource endpoint, credentials, or deployment name in
this request. This table describes common fields, not every SDK option.

Example response: **200 OK**, abbreviated:

```json
{
  "id": "caresp_example_001",
  "object": "response",
  "status": "completed",
  "created_at": 1793828058,
  "completed_at": 1793828067,
  "output": [
    {
      "type": "function_call",
      "call_id": "call_example_001",
      "name": "rectangle_area",
      "arguments": "{\"length\":3,\"width\":4}",
      "status": "completed"
    },
    {
      "type": "function_call_output",
      "call_id": "call_example_001",
      "output": "Area = length * width = 3.0 * 4.0 = 12.0 square units.",
      "status": "completed"
    },
    {
      "type": "message",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "Area = length * width = 3 cm * 4 cm = 12 square centimeters."
        }
      ],
      "status": "completed"
    }
  ],
  "usage": {
    "input_tokens": 5740,
    "input_tokens_details": {
      "cached_tokens": 5504
    },
    "output_tokens": 329,
    "output_tokens_details": {
      "reasoning_tokens": 192
    },
    "total_tokens": 6069
  },
  "background": false
}
```

Reasoning items, encrypted content, item IDs, and other metadata are omitted
from this example. Function arguments are a JSON-encoded **string**, not an
object. The observed live sample contained duplicated argument JSON; that is
an unresolved anomaly, not an expected format or a behavior clients should copy.

### Reading the response

| Field/item | Meaning |
|---|---|
| `id` / `response_id` | Response identifier; use the returned `id` for retrieval or continuation |
| `object` | `"response"` identifies the envelope |
| `status` | Execution state; HTTP 200 alone does not establish a successful completed answer |
| `created_at` / `completed_at` | Unix timestamps |
| `output[].type: reasoning` | Opaque model reasoning items; encrypted content is not answer text |
| `output[].type: function_call` | Requested tool name and JSON-encoded arguments |
| `output[].type: function_call_output` | Tool result, matched by `call_id` |
| `output[].type: message` | Assistant message; read `content` items of type `output_text` |
| `usage` | Token accounting across the agent's model calls |
| `agent_reference` | Host-provided agent identity metadata |
| `agent_session_id` | SDK-managed session identifier |
| `parallel_tool_calls` | Whether parallel tool calling was enabled |
| `model` | May be empty in the host envelope; this does not mean no model was used |

Do not assume `output[0]` contains the answer: reasoning and tool items can
precede assistant messages. [chat.py](chat.py) collects the message text,
requires `status: completed`, and explicitly reports incomplete/failed results
or refusals.

Cached input tokens are included in `input_tokens`; reasoning tokens are
included in `output_tokens`. Do not add detail counts a second time.
Token counts are not a price quote; billing depends on the deployed model.

### Follow-up request

Use the real ID from the previous stored response:

```json
{
  "input": "What if the width were 5 cm instead?",
  "previous_response_id": "caresp_example_001",
  "stream": false,
  "store": true
}
```

Example response: **200 OK**, abbreviated:

```json
{
  "id": "caresp_example_002",
  "object": "response",
  "status": "completed",
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "Keeping the length at 3 cm, the new area is 3 * 5 = 15 square centimeters."
        }
      ]
    }
  ]
}
```

Omit `previous_response_id` to start a new conversation. The CLI's `clear`
command does this; it does not delete earlier stored responses.

### Supply conversation input directly

Instead of referencing a stored response, provide protocol message items:

```json
{
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": "My circle has radius 2 cm."
    },
    {
      "type": "message",
      "role": "assistant",
      "content": "I will use a radius of 2 cm."
    },
    {
      "type": "message",
      "role": "user",
      "content": "What is its area?"
    }
  ],
  "stream": false,
  "store": true
}
```

The result uses the same response envelope. A correct answer is approximately
12.56637 square centimeters; exact wording is model-dependent.

### Streaming request

```json
{
  "input": "Explain how to calculate the area of a rectangle.",
  "stream": true,
  "store": true
}
```

Example response: **200 OK**, content type `text/event-stream`.
An illustrative excerpt, with protocol metadata and intervening events omitted:

```text
data: {"type":"response.created","response":{"id":"caresp_example_003","status":"in_progress"}}

data: {"type":"response.output_text.delta","delta":"Multiply the length"}

data: {"type":"response.output_text.delta","delta":" by the width."}

data: {"type":"response.completed","response":{"id":"caresp_example_003","status":"completed"}}
```

Use an SSE-aware client, handle terminal failures/incomplete responses, and do
not assume every event is text. Tool and reasoning events can also be present.
Swagger is simplest with `stream: false`; it is not a full streaming chat UI.

### Background request

```json
{
  "input": "Explain the steps for solving x^2 - 5*x + 6 = 0.",
  "background": true,
  "store": true,
  "stream": false
}
```

An accepted background response returns **200 OK** with a response ID and a
nonterminal status such as `queued` or `in_progress`. Poll
`GET /responses/{response_id}` for its current state.

Background work and local file-based storage are not a crash-durability
guarantee in this starter. See [SDK storage limitations](README.md#dependency-compatibility)
before relying on long-running work.

## 3. GET /responses/{response_id}

No request body. Use the ID of an existing stored response.

```powershell
Invoke-RestMethod "http://localhost:8088/responses/$responseId"
```

Example response: **200 OK**, abbreviated:

```json
{
  "id": "caresp_example_001",
  "object": "response",
  "status": "completed",
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "The area is 12 square centimeters."
        }
      ]
    }
  ]
}
```

Retrieval does not create another model response. Missing/deleted response IDs
can return 404. Retrieval depends on the configured SDK store.

## 4. GET /responses/{response_id}/input_items

No request body.

```powershell
Invoke-RestMethod "http://localhost:8088/responses/$responseId/input_items?limit=20&order=asc"
```

Supported query fields in the current SDK:

| Parameter | Meaning |
|---|---|
| `limit` | Integer 1-100; default 20 |
| `order` | `asc` or `desc`; default `desc` |
| `after` / `before` | Item-ID pagination cursors |

Example response: **200 OK**, abbreviated:

```json
{
  "object": "list",
  "data": [
    {
      "id": "msg_example_input_001",
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "Find the area of a rectangle 3 cm by 4 cm."
        }
      ]
    }
  ],
  "first_id": "msg_example_input_001",
  "last_id": "msg_example_input_001",
  "has_more": false
}
```

The item representation depends on the stored input. Pagination IDs can be
null for an empty page or items without IDs.

## 5. POST /responses/{response_id}/cancel

No request body. Only background responses are cancellable.

```powershell
Invoke-RestMethod -Method Post "http://localhost:8088/responses/$backgroundResponseId/cancel"
```

Example successful response: **200 OK**, abbreviated:

```json
{
  "id": "caresp_example_background_001",
  "object": "response",
  "status": "cancelled",
  "background": true,
  "output": []
}
```

Cancellation can race completion; a completed response cannot be cancelled.
Cancelling a synchronous response returns a client error rather than undoing
an answer already returned.

## 6. DELETE /responses/{response_id}

No request body.

```powershell
Invoke-RestMethod -Method Delete "http://localhost:8088/responses/$responseId"
```

Example response: **200 OK**

```json
{
  "id": "caresp_example_001",
  "object": "response",
  "deleted": true
}
```

Deletion removes that stored response; do not subsequently use it for retrieval
or continuation. This is different from starting a new conversation.

## 7. Optional Swagger and OpenAPI

In `.env`:

```dotenv
ENABLE_SWAGGER=true
```

Restart `python main.py`:

- **GET http://localhost:8088/docs** returns the Swagger HTML page.
- **GET http://localhost:8088/openapi.json** returns its OpenAPI 3.0.3 document.

These routes document the existing server; they do not create a second API.
Swagger lists the endpoints in this guide and provides a sample `POST /responses`
request. Its schema documents common fields, not every SDK protocol option.
The browser downloads pinned Swagger UI assets from jsDelivr.

Set `ENABLE_SWAGGER=false` and restart to remove both routes (404).
False is the default when unset. Keep documentation disabled in hosted
deployments unless deliberately enabled. Process environment values take
precedence over `.env`; invalid values other than true/false fail startup.

## 8. Errors and status handling

Check both the HTTP result and the response body's execution `status`.
An accepted/background or failed execution is not necessarily a completed answer.
Streaming failures can arrive as events after the HTTP connection succeeds.

Example **404** envelope for a missing response, abbreviated:

```json
{
  "error": {
    "code": "invalid_request_error",
    "message": "Response with id 'caresp_example_missing' not found.",
    "param": "response_id",
    "type": "invalid_request_error"
  }
}
```

| Condition | Handling |
|---|---|
| Malformed JSON or invalid protocol parameters | Inspect the 400/422 validation response; correct the request |
| Missing/deleted stored response | Inspect the 404 response; use an existing returned ID |
| Invalid mode, such as `background: true` with `store: false` | Correct the incompatible parameters |
| Azure credentials, RBAC, model configuration, quota, or upstream failure | Inspect the returned error/status and server logs; readiness alone does not rule these out |
| Swagger routes return 404 | Enable `ENABLE_SWAGGER=true` and restart the correct server/port |

Exact messages, metadata, and status codes depend on the failing SDK/upstream
operation. Do not silently substitute an empty answer after an error.

## 9. PowerShell walkthrough

With the server running and model access configured:

```powershell
$base = 'http://localhost:8088'
Invoke-RestMethod "$base/readiness"

# This and the follow-up invoke the model and can incur charges.
$first = Invoke-RestMethod -Method Post -Uri "$base/responses" `
    -ContentType 'application/json' `
    -Body (@{ input = 'Find the area of a rectangle 3 cm by 4 cm.'; stream = $false; store = $true } | ConvertTo-Json)
$responseId = $first.id
$first.output | ConvertTo-Json -Depth 20

$followUp = Invoke-RestMethod -Method Post -Uri "$base/responses" `
    -ContentType 'application/json' `
    -Body (@{ input = 'What if the width were 5 cm?'; previous_response_id = $responseId; stream = $false; store = $true } | ConvertTo-Json)
$followUp.output | ConvertTo-Json -Depth 20

Invoke-RestMethod "$base/responses/$responseId"
Invoke-RestMethod "$base/responses/$responseId/input_items?order=asc"

# Optional: remove the stored responses after testing.
Invoke-RestMethod -Method Delete "$base/responses/$($followUp.id)"
Invoke-RestMethod -Method Delete "$base/responses/$responseId"
```

For interactive terminal conversations instead, run `python chat.py`.
