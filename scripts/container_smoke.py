"""Check a running hosted container without sending a model inference request."""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> None:
    base = "http://127.0.0.1:18088"
    deadline = time.monotonic() + 90
    while True:
        try:
            with urlopen(f"{base}/readiness", timeout=5) as response:
                if response.status != 200:
                    raise RuntimeError(f"Unexpected readiness status: {response.status}")
            break
        except (URLError, TimeoutError, ConnectionError) as error:
            if time.monotonic() >= deadline:
                raise TimeoutError("Container did not become ready in 90 seconds") from error
            print(f"Waiting for container: {error}", flush=True)
            time.sleep(2)
    request = Request(f"{base}/responses", data=b"{", headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=5):
            raise RuntimeError("Malformed Responses input was incorrectly accepted")
    except HTTPError as error:
        if error.code not in (400, 422):
            raise
        json.loads(error.read())
    print("Container readiness and malformed-input checks passed; no inference requested.")


if __name__ == "__main__":
    main()
