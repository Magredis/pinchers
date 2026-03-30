import json
import os
import re
import requests

CLIENT_ID = os.environ["YAHOO_CLIENT_ID"]
CLIENT_SECRET = os.environ["YAHOO_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["YAHOO_REFRESH_TOKEN"]
LEAGUE_ID = "43533"
GAME_KEY = "mlb"
DATA_FILE = "data/weeks.json"


def get_tokens():
    r = requests.post("https://api.login.yahoo.com/oauth2/get_token", data={
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    r.raise_for_status()
    data = r.json()
    return data["access_token"], data.get("refresh_token", REFRESH_TOKEN)


def yahoo_api(token, endpoint):
    r = requests.get(
        f"https://fantasysports.yahooapis.com/fantasy/v2{endpoint}?format=json",
        headers={"Authorization": f"Bearer {token}"}
    )
    r.raise_for_status()
    return r.json()


def parse_team(info):
    name = team_id = mgr = div = ""
    for item in info:
        if isinstance(item, dict):
            if "name" in item:
                name = item["name"]
            if "team_id" in item:
                team_id = item["team_id"]
            if "division_id" in item:
                div = item["division_id"]
            if "managers" in item:
                mgrs = item["managers"]
                if mgrs and isinstance(mgrs, list) and "manager" in mgrs[0]:
                    mgr = mgrs[0]["manager"].get("nickname", "")
    return name, team_id, mgr, div


def parse_standings(data):
    league = data["fantasy_content"]["league"]
    league_info = league[0]
    current_week = int(league_info.get("current_week", 1))

    standings_obj = league[1]["standings"][0]["teams"]
    count = standings_obj.get("count", 0)
    teams = []

    for i in range(count):
        t = standings_obj[str(i)]["team"]
        name, team_id, mgr, div = parse_team(t[0])

        ts = t[2].get("team_standings", {})
        ot = ts.get("outcome_totals", {})

        stats = {}
        for s in t[1].get("team_stats", {}).get("stats", []):
            if "stat" in s:
                stats[s["stat"]["stat_id"]] = s["stat"]["value"]

        teams.append({
            "id": int(team_id),
            "name": name,
            "mgr": mgr,
            "div": int(div) if div else 0,
            "rank": int(ts.get("rank", i + 1)),
            "w": int(ot.get("wins", 0)),
            "l": int(ot.get("losses", 0)),
            "t": int(ot.get("ties", 0)),
            "pct": ot.get("percentage", ".000"),
            "stats": stats,
        })

    # Mark user's team
    for t in teams:
        if t["id"] == 2:
            t["you"] = True

    return teams, current_week


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_index_html(data):
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Find and replace WEEKS_DATA block
    start_marker = "const WEEKS_DATA = "
    start_idx = html.find(start_marker)
    if start_idx == -1:
        print("ERROR: Could not find WEEKS_DATA in index.html")
        return

    brace_start = html.find("{", start_idx)
    depth = 0
    end_idx = brace_start
    for ci in range(brace_start, len(html)):
        if html[ci] == "{":
            depth += 1
        elif html[ci] == "}":
            depth -= 1
        if depth == 0:
            end_idx = ci
            break

    semi_idx = html.find(";", end_idx)
    if semi_idx == -1:
        semi_idx = end_idx

    json_str = json.dumps(data, ensure_ascii=False)
    new_html = html[:start_idx] + f"const WEEKS_DATA = {json_str};" + html[semi_idx + 1:]

    # Update period dropdowns (both league and h2h)
    week_keys = sorted([k for k in data.keys() if k != "season"], key=lambda x: int(x), reverse=True)
    options = '<option value="season">Season total</option>\n'
    for wk in week_keys:
        options += f'    <option value="{wk}">Week {wk}</option>\n'

    for select_id in ["period", "period-h2h"]:
        pattern = rf'(<select id="{select_id}"[^>]*>)(.*?)(</select>)'
        replacement = f"\\1\n    {options}  \\3"
        new_html = re.sub(pattern, replacement, new_html, flags=re.DOTALL)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(new_html)

    print("Updated index.html")


def main():
    print("Getting fresh tokens...")
    access_token, new_refresh_token = get_tokens()
    print("Got access token")

    if new_refresh_token != REFRESH_TOKEN:
        print("New refresh token received")
        gh_output = os.environ.get("GITHUB_OUTPUT")
        if gh_output:
            with open(gh_output, "a") as f:
                f.write(f"new_refresh_token={new_refresh_token}\n")

    print("Fetching standings...")
    standings_data = yahoo_api(access_token, f"/league/{GAME_KEY}.l.{LEAGUE_ID}/standings")
    teams, current_week = parse_standings(standings_data)

    completed_week = current_week - 1
    if completed_week < 1:
        print("No completed weeks yet")
        return

    print(f"Current week: {current_week}, saving week: {completed_week}")

    data = load_data()
    data["season"] = teams
    data[str(completed_week)] = teams

    save_data(data)
    print(f"Saved to {DATA_FILE}")

    update_index_html(data)
    print("Done!")


if __name__ == "__main__":
    main()
