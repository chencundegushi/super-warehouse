"""Test SSE confirm endpoint directly"""
import httpx
import sys

session_id = sys.argv[1] if len(sys.argv) > 1 else "test-session"

with httpx.stream(
    "POST",
    "http://localhost:8000/api/chat/confirm",
    json={"sessionId": session_id, "confirmed": True},
    headers={"Accept": "text/event-stream"},
    timeout=30,
) as response:
    print(f"Status: {response.status_code}")
    print(f"Headers: {dict(response.headers)}")
    for line in response.iter_lines():
        print(f"LINE: {repr(line)}")
    print("STREAM ENDED")
