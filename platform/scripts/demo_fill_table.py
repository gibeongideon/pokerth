"""Fill your demo table with bot opponents (LOCAL TESTING ONLY).

On the phone (demo APK, signed in as alice) tap Quick play or open a table.
Then run on the computer:

    platform/.venv/bin/python platform/scripts/demo_fill_table.py [player]

It seats other demo players (bob, carol, ...) at the table `player` is
waiting at, marks them ready, waits until you press "I'M READY" on the phone,
then starts C++ bots that play their seats over the real game server.
Needs platform/scripts/run_lan_demo.sh running (API on :8000, PLATFORM_ENV=local).
"""

import subprocess
import sys
import time

import httpx

API = "http://localhost:8000"
DEMO = ["bob", "carol", "dave", "erin", "frank", "grace", "alice"]


def main() -> None:
    me = sys.argv[1] if len(sys.argv) > 1 else "alice"
    c = httpx.Client(base_url=API, timeout=10)
    tokens: dict[str, str] = {}

    def h(user: str) -> dict[str, str]:
        if user not in tokens:
            r = c.post(f"/dev/token/{user}")
            r.raise_for_status()
            tokens[user] = r.json()["access_token"]
        return {"Authorization": f"Bearer {tokens[user]}"}

    mine = [t for t in c.get("/tables/mine", headers=h(me)).json() if t["status"] in ("open", "ready_check")]
    if not mine:
        sys.exit(f"{me} isn't waiting at a table. Tap Quick play (or open a table) on the phone first.")
    table = mine[0]
    print(f"table {table['id']} ({table['price_label']}): {table['players']}/{table['seats_total']} seated")

    others = [u for u in DEMO if u != me]
    seated: list[str] = []
    for user in others:
        t = c.get(f"/tables/{table['id']}", headers=h(me)).json()
        if t["players"] >= t["seats_total"] or t["status"] != "open":
            break
        body = {"invite_code": t.get("invite_code")}
        r = c.post(f"/tables/{table['id']}/join", json=body, headers=h(user))
        if r.status_code < 300:
            seated.append(user)
            print(f"  {user} sat down")
        else:
            print(f"  {user} couldn't join: {r.json().get('detail', r.text)}")

    print("waiting for the ready check ...")
    for _ in range(60):
        t = c.get(f"/tables/{table['id']}", headers=h(me)).json()
        if t["status"] == "ready_check":
            break
        time.sleep(1)
    for user in seated:
        c.post(f"/tables/{table['id']}/ready", headers=h(user))
    print(">>> Now tap I'M READY on the phone.")

    for _ in range(180):
        t = c.get(f"/tables/{table['id']}", headers=h(me)).json()
        if t["status"] == "running":
            break
        if t["status"] in ("cancelled", "finished"):
            sys.exit(f"table is {t['status']}")
        time.sleep(1)
    else:
        sys.exit("you didn't press ready in time")

    seat_tokens = [c.get(f"/tables/{table['id']}/seat-token", headers=h(u)).json()["token"] for u in seated]
    subprocess.run(["docker", "rm", "-f", "poker-bots"], capture_output=True)
    subprocess.run(
        ["docker", "run", "-d", "--name", "poker-bots", "--network", "host", "-v", "poker-server-build-cache:/build:ro",
         "poker-server-build", "/build/bin/pokerth_bot", "-s", "127.0.0.1", "--no-tls", "--platform-tokens", ",".join(seat_tokens)],
        check=True, capture_output=True,
    )
    print(f"{len(seated)} bots are playing. Good luck! (stop them: docker rm -f poker-bots)")


if __name__ == "__main__":
    main()
