"""Create a local Google Calendar token for Deadline Relay.

Run manually after downloading a Desktop OAuth client JSON file. This script never
creates calendars or events and requests only owned-event and free/busy scopes.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = (
    "https://www.googleapis.com/auth/calendar.events.owned",
    "https://www.googleapis.com/auth/calendar.freebusy",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize Deadline Relay for a dedicated owned calendar")
    parser.add_argument(
        "--client-secrets", type=Path, required=True, help="Downloaded Desktop OAuth client JSON"
    )
    parser.add_argument("--token", type=Path, required=True, help="Output token path outside source control")
    args = parser.parse_args()
    if not args.client_secrets.is_file():
        parser.error("--client-secrets must name an existing file")
    flow = InstalledAppFlow.from_client_secrets_file(str(args.client_secrets), SCOPES)
    credentials = flow.run_local_server(host="127.0.0.1", port=0, access_type="offline", prompt="consent")
    args.token.parent.mkdir(parents=True, exist_ok=True)
    args.token.write_text(credentials.to_json(), encoding="utf-8")
    print(f"Authorized token written to {args.token}. Set GOOGLE_TOKEN_PATH to this path.")


if __name__ == "__main__":
    main()
