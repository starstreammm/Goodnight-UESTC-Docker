"""Start the public proxy only after the backend has finished initialization."""

import os
import time
import urllib.error
import urllib.request


def main():
    deadline = time.monotonic() + 60
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with opener.open("http://127.0.0.1:8000/api/health", timeout=1) as response:
                if response.status == 200:
                    os.execv("/usr/sbin/nginx", ["nginx", "-g", "daemon off;"])
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    raise SystemExit("Backend readiness timed out; supervisor will retry the proxy.")


if __name__ == "__main__":
    main()
