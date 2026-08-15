from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


HOST = "127.0.0.1"
PORT = 18082
BASE_URL = f"http://{HOST}:{PORT}"
DEFAULT_USER_ID = "acceptance-08e2-6c744aa142"
DEFAULT_NOVEL_ID = "85c4dff6-7530-459f-a3f7-1eaf34fc5c76"


def request_status(path: str, token: str | None = None) -> int:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(BASE_URL + path, headers=headers)
    try:
        return urllib.request.urlopen(request, timeout=10).status
    except urllib.error.HTTPError as exc:
        return exc.code


def wait_until_ready(process: subprocess.Popen[bytes]) -> None:
    for _ in range(90):
        if process.poll() is not None:
            raise RuntimeError("isolated auth server exited before readiness")
        try:
            if request_status("/api/v1/health") == 200:
                return
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError("isolated auth server did not become ready")


def main() -> int:
    owner_user_id = os.getenv("AUTH_ACCEPTANCE_USER_ID", DEFAULT_USER_ID)
    novel_id = os.getenv("AUTH_ACCEPTANCE_NOVEL_ID", DEFAULT_NOVEL_ID)
    user_token = secrets.token_hex(32)
    other_token = secrets.token_hex(32)
    admin_token = secrets.token_hex(32)

    token_map = {
        user_token: {"user_id": owner_user_id, "roles": ["user"]},
        other_token: {"user_id": "auth-runtime-other", "roles": ["user"]},
        admin_token: {"user_id": "auth-runtime-admin", "roles": ["admin"]},
    }
    child_env = os.environ.copy()
    child_env["AUTH_ENABLED"] = "true"
    child_env["AUTH_TOKENS_JSON"] = json.dumps(token_map, separators=(",", ":"))

    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                HOST,
                "--port",
                str(PORT),
            ],
            cwd="/app",
            env=child_env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_until_ready(process)
            values: dict[str, str | int] = {
                "health": request_status("/api/v1/health"),
                "anonymous": request_status("/api/v1/providers"),
                "authenticated": request_status("/api/v1/providers", user_token),
                "mismatch": request_status(
                    "/api/v1/novels?user_id=auth-runtime-other",
                    user_token,
                ),
                "owned": request_status(f"/api/v1/novels/{novel_id}", user_token),
                "hidden": request_status(f"/api/v1/novels/{novel_id}", other_token),
                "user_ops": request_status("/api/v1/workflows/workers", user_token),
                "admin_ops": request_status("/api/v1/workflows/workers", admin_token),
            }
            identity_request = urllib.request.Request(
                BASE_URL + "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            identity = json.load(
                urllib.request.urlopen(identity_request, timeout=10)
            )["data"]
            values["identity"] = identity["user_id"]

            expected: dict[str, str | int] = {
                "health": 200,
                "anonymous": 401,
                "authenticated": 200,
                "mismatch": 403,
                "owned": 200,
                "hidden": 404,
                "user_ops": 403,
                "admin_ops": 200,
                "identity": owner_user_id,
            }
            print(json.dumps(values, ensure_ascii=False, sort_keys=True))
            if values != expected:
                raise RuntimeError("auth runtime acceptance matrix mismatch")
            print("AUTH RUNTIME ACCEPTANCE: PASS")
            return 0
        except Exception:
            log.seek(0)
            output = log.read().decode("utf-8", errors="replace")
            if output:
                print(output[-8000:], file=sys.stderr)
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
