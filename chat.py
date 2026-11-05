"""Interactive HTTP client for the local math tutor Responses server."""

import argparse
import os

import httpx
from dotenv import load_dotenv


BANNER = """
Math Tutor - Arithmetic, Geometry, and Algebra

Examples:
  What is the area of a circle with radius 5 cm?
  Find the hypotenuse of a right triangle with legs 3 and 4.
  Solve x^2 - 5*x + 6 = 0.

Commands: help | status | clear | quit
"""


def response_message(data: object) -> tuple[str, str]:
    """Validate a completed Responses result and collect assistant text."""
    if not isinstance(data, dict):
        raise ValueError("Server returned a non-object response.")
    if data.get("status") != "completed":
        details = data.get("error") or data.get("incomplete_details")
        raise ValueError(f"Response was not completed: {data.get('status')}; {details}")
    response_id = data.get("id")
    output = data.get("output")
    if not isinstance(response_id, str) or not response_id or not isinstance(output, list):
        raise ValueError("Server response is missing an id or output list.")
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            raise ValueError("Server message is missing a content list.")
        for part in content:
            if not isinstance(part, dict):
                raise ValueError("Server returned invalid message content.")
            if part.get("type") == "refusal":
                raise ValueError(f"Tutor refused the request: {part.get('refusal')}")
            if part.get("type") == "output_text":
                text = part.get("text")
                if not isinstance(text, str):
                    raise ValueError("Server returned invalid output text.")
                texts.append(text)
    text = "\n".join(texts)
    if not text.strip():
        raise ValueError("Tutor returned no text.")
    return response_id, text


def run_chat(client: httpx.Client) -> None:
    print(BANNER)
    previous_response_id: str | None = None
    while True:
        try:
            message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message:
            continue
        command = message.lower()
        if command in ("quit", "exit", "bye"):
            break
        if command == "help":
            print(BANNER)
        elif command == "clear":
            previous_response_id = None
            print("Started a new conversation. Earlier responses remain stored on the server.")
        else:
            try:
                if command == "status":
                    client.get("/readiness", timeout=5).raise_for_status()
                    print("Math tutor server is ready; model access is checked when you ask a question.")
                    continue
                payload: dict[str, object] = {
                    "input": message,
                    "stream": False,
                    "store": True,
                }
                if previous_response_id is not None:
                    payload["previous_response_id"] = previous_response_id
                response = client.post("/responses", json=payload)
                response.raise_for_status()
                response_id, text = response_message(response.json())
                previous_response_id = response_id
                print(f"Tutor: {text}")
            except (httpx.HTTPError, ValueError) as exc:
                print(f"Tutor request failed: {exc}")
    print("Goodbye!")


def main() -> int:
    load_dotenv(override=False)
    port = os.getenv("PORT") or os.getenv("DEFAULT_AD_PORT", "8088")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=f"http://127.0.0.1:{port}", help="Responses server base URL")
    args = parser.parse_args()
    try:
        with httpx.Client(base_url=args.url, timeout=180) as client:
            client.get("/readiness", timeout=5).raise_for_status()
            print(f"Connected to {args.url}")
            run_chat(client)
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
        print(f"Cannot use the math tutor server: {exc}\nStart it first with: python main.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
