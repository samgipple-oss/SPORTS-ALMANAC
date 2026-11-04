
#!/usr/bin/env python3
"""Sports Almanac — automatic sports fixtures and TV schedule matching."""

import concurrent.futures
import datetime as dt
import difflib
import gzip
import json
import os
import pathlib
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "sports-fixtures.json"
OVERRIDES = ROOT / "broadcast-overrides.json"
CHANNELS = ROOT / "xmltv-channels.json"

UTC = dt.timezone.utc

LEAGUES = [
    ("Basketball", "NBA", "basketball/nba"),
    ("Basketball", "WNBA", "basketball/wnba"),
    ("Baseball", "MLB", "baseball/mlb"),
    ("American football", "NFL", "football/nfl"),
    ("Ice hockey", "NHL", "hockey/nhl"),
    ("Football", "Premier League", "soccer/eng.1"),
    ("Football", "Champions League", "soccer/uefa.champions"),
    ("Football", "Europa League", "soccer/uefa.europa"),
    ("Football", "MLS", "soccer/usa.1"),
    ("Football", "La Liga", "soccer/esp.1"),
    ("Football", "Bundesliga", "soccer/ger.1"),
    ("Football", "Serie A", "soccer/ita.1"),
    ("Football", "WSL", "soccer/eng.w.1"),
    ("Football", "Women’s Champions League", "soccer/uefa.wchampions"),
    ("Football", "UEFA Nations League", "soccer/uefa.nations"),
]

NETWORKS = {
    "ABC": "ABC",
    "CBS": "CBS",
    "FOX": "FOX",
    "NBC": "NBC",
    "ESPN": "ESPN",
    "ESPN2": "ESPN2",
    "ESPN+": "ESPN+",
    "PEACOCK": "Peacock",
    "PRIME VIDEO": "Prime Video",
    "AMAZON PRIME VIDEO": "Prime Video",
    "NBA TV": "NBA TV",
    "TNT": "TNT",
    "TBS": "TBS",
    "FS1": "FS1",
    "PARAMOUNT+": "Paramount+",
    "APPLE TV": "Apple TV",
    "NFL NETWORK": "NFL Network",
    "MLB NETWORK": "MLB Network",
    "NHL NETWORK": "NHL Network",
}

UK_CHANNELS = {
    "sky sports": "Sky Sports",
    "tnt sports": "TNT Sports",
    "premier sports": "Premier Sports",
    "bbc one": "BBC iPlayer",
    "bbc two": "BBC iPlayer",
    "bbc three": "BBC iPlayer",
    "bbc four": "BBC iPlayer",
    "bbc1": "BBC iPlayer",
    "bbc2": "BBC iPlayer",
    "itv1": "ITVX",
    "itv2": "ITVX",
    "itv3": "ITVX",
    "itv4": "ITVX",
    "channel 4": "Channel 4",
    "channel 5": "Channel 5",
    "5action": "Channel 5",
    "5 action": "Channel 5",
}


def get_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "SportsAlmanac/2.1",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def iso(value):
    return dt.datetime.fromisoformat(
        value.replace("Z", "+00:00")
    ).astimezone(UTC)


def team_name(competitor):
    team = competitor.get("team") or {}

    return (
        team.get("displayName")
        or team.get("name")
        or "TBC"
    )


def espn_leads(event, competition, url):
    names = []

    for obj in (competition, event):
        for entry in obj.get("broadcasts", []) or []:
            if isinstance(entry, str):
                names.append(entry)

            elif isinstance(entry, dict):
                names.extend(entry.get("names", []) or [])

                if entry.get("name"):
                    names.append(entry["name"])

        for entry in obj.get("geoBroadcasts", []) or []:
            if isinstance(entry, dict):
                media = entry.get("media") or {}

                if isinstance(media, dict):
                    names.append(media.get("shortName", ""))

    found = []
    seen = set()

    for name in names:
        service = NETWORKS.get(str(name).strip().upper())

        if service and service not in seen:
            found.append({
                "country": "US",
                "service": service,
                "verified": False,
                "basis": "event-schedule",
                "sourceUrl": url,
                "note": (
                    "Listed for this game by ESPN; "
                    "access and blackouts unverified"
                ),
            })

            seen.add(service)

    return found


def fetch_day(job):
    sport, league, path, day = job

    params = urllib.parse.urlencode({
        "dates": day.strftime("%Y%m%d"),
        "limit": 300,
    })

    url = (
        "https://site.api.espn.com/apis/site/v2/sports/"
        f"{path}/scoreboard?{params}"
    )

    try:
        data = get_json(url)

        if not isinstance(data.get("events"), list):
            raise ValueError("Missing events array")

        games = []

        for event in data["events"]:
            try:
                competition = event["competitions"][0]
                competitors = competition["competitors"]

                home = next(
                    x for x in competitors
                    if x.get("homeAway") == "home"
                )

                away = next(
                    x for x in competitors
                    if x.get("homeAway") == "away"
                )

                start = iso(event["date"])

                games.append({
                    "id": f"espn:{path}:{event['id']}",
                    "sport": sport,
                    "competition": league,
                    "title": (
                        f"{team_name(away)} at {team_name(home)}"
                    ),
                    "homeTeam": team_name(home),
                    "awayTeam": team_name(away),
                    "start": start.isoformat().replace(
                        "+00:00", "Z"
                    ),
                    "liveStatus": (
                        event.get("status", {})
                        .get("type", {})
                        .get("description", "Scheduled")
                    ),
                    "fixtureSource": url,
                    "broadcasts": [],
                    "broadcastLeads": espn_leads(
                        event, competition, url
                    ),
                })

            except (
                KeyError,
                IndexError,
                StopIteration,
                TypeError,
                ValueError,
            ):
                continue

        return games, None

    except Exception as exc:
        return [], f"{path} {day}: {exc}"


def normalise(value):
    value = str(value).casefold()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)

    ignored = {"fc", "afc", "cf", "the"}

    return " ".join(
        word for word in value.split()
        if word not in ignored
    )


def team_in_text(team, text):
    target = normalise(team)
    content = normalise(text)

    if not target or not content:
        return False

    if re.search(
        r"\b" + re.escape(target) + r"\b",
        content,
    ):
        return True

    if len(target) < 8 or len(target.split()) < 2:
        return False

    target_words = target.split()
    content_words = content.split()

    fragments = [
        " ".join(
            content_words[i:i + len(target_words)]
        )
        for i in range(
            max(
                0,
                len(content_words) - len(target_words) + 1,
            )
        )
    ]

    return any(
        difflib.SequenceMatcher(
            None, target, fragment
        ).ratio() >= 0.92
        for fragment in fragments
    )


def xmltv_time(value):
    value = value.strip()

    if re.fullmatch(r"\d{14}", value):
        return dt.datetime.strptime(
            value, "%Y%m%d%H%M%S"
        ).replace(tzinfo=UTC)

    return dt.datetime.strptime(
        value, "%Y%m%d%H%M%S %z"
    ).astimezone(UTC)


def discover_channels(root):
    """Identify UK services from actual XMLTV channel names."""

    discovered = {}

    for channel in root.findall("channel"):
        channel_id = channel.get("id", "")

        names = [
            (element.text or "").strip()
            for element in channel.findall("display-name")
        ]

        for name in names:
            name_lower = name.casefold()

            for prefix, service in UK_CHANNELS.items():
                if name_lower.startswith(prefix):
                    discovered[channel_id] = {
                        "country": "UK",
                        "service": service,
                    }
                    break

            if channel_id in discovered:
                break

    print(
        f"Automatically identified "
        f"{len(discovered)} UK broadcaster channels"
    )

    return discovered


def load_xmltv(games):
    url = os.environ.get("XMLTV_URL", "").strip()

    if not url:
        print(
            "XMLTV_URL not set: "
            "skipping external TV listings"
        )
        return 0

    config = (
        json.loads(CHANNELS.read_text(encoding="utf-8"))
        if CHANNELS.exists()
        else {}
    )

    if not isinstance(config, dict):
        raise ValueError(
            "xmltv-channels.json must contain a JSON object"
        )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "SportsAlmanac/2.1"
        },
    )

    with urllib.request.urlopen(
        request, timeout=40
    ) as response:
        raw = response.read(20_000_001)

    if len(raw) > 20_000_000:
        raise ValueError(
            "XMLTV feed exceeds 20 MB download limit"
        )

    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)

        if len(raw) > 30_000_000:
            raise ValueError(
                "Decompressed XMLTV feed exceeds 30 MB"
            )

    root = ET.fromstring(raw)

    discovered = discover_channels(root)

    # Manual mappings override automatically discovered ones.
    config = {
        **discovered,
        **config,
    }

    by_day = {}

    for game in games:
        date = iso(game["start"]).date()

        by_day.setdefault(date, []).append(game)

    matched = 0

    for programme in root.findall(".//programme"):
        channel_id = programme.get("channel", "")
        channel = config.get(channel_id)

        if not isinstance(channel, dict):
            continue

        country = channel.get("country")
        service = channel.get("service")

        if country not in ("UK", "US") or not service:
            continue

        try:
            start = xmltv_time(
                programme.attrib["start"]
            )

        except (ValueError, KeyError):
            continue

        title = " ".join(
            (element.text or "")
            for element in programme.findall("title")
        )

        description = " ".join(
            (element.text or "")
            for element in programme.findall("desc")
        )

        content = f"{title} {description}"

        candidates = (
            by_day.get(start.date(), [])
            + by_day.get(
                (start - dt.timedelta(days=1)).date(), []
            )
            + by_day.get(
                (start + dt.timedelta(days=1)).date(), []
            )
        )

        for game in candidates:
            game_start = iso(game["start"])

            # Broadcast may begin up to four hours before
            # kickoff, or up to 30 minutes afterwards.
            difference = (
                start - game_start
            ).total_seconds()

            if not (-14400 <= difference <= 1800):
                continue

            # Require both teams to appear in the listing.
            if not team_in_text(
                game["homeTeam"], content
            ):
                continue

            if not team_in_text(
                game["awayTeam"], content
            ):
                continue

            entry = {
                "country": country,
                "service": service,
                "verified": False,
                "basis": "matched-tv-listing",
                "sourceUrl": channel.get(
                    "sourceUrl", url
                ),
                "programmeTitle": title,
                "programmeStart": (
                    start.isoformat().replace("+00:00", "Z")
                ),
                "note": (
                    "Both teams matched an XMLTV programme "
                    "near kickoff; broadcaster access "
                    "still requires confirmation"
                ),
            }

            existing = game["broadcastLeads"]

            if not any(
                item["country"] == country
                and item["service"] == service
                for item in existing
            ):
                existing.append(entry)
                matched += 1

    return matched


def valid_override(item):
    return (
        isinstance(item, dict)
        and item.get("country") in ("UK", "US")
        and isinstance(item.get("service"), str)
        and bool(item["service"].strip())
        and item.get("verified") is True
        and isinstance(item.get("sourceUrl"), str)
        and item["sourceUrl"].startswith("https://")
    )


def main():
    now = dt.datetime.now(UTC)
    today = now.date()

    jobs = [
        (
            sport,
            league,
            path,
            today + dt.timedelta(days=i),
        )
        for sport, league, path in LEAGUES
        for i in range(32)
    ]

    all_games = []
    errors = []

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=10
    ) as pool:
        for games, error in pool.map(
            fetch_day, jobs
        ):
            all_games.extend(games)

            if error:
                errors.append(error)

    unique = {}

    for game in all_games:
        start = iso(game["start"])

        if now <= start < now + dt.timedelta(days=30):
            unique[game["id"]] = game

    if not unique:
        raise RuntimeError(
            "No fixtures retrieved; keeping old database"
        )

    overrides = (
        json.loads(
            OVERRIDES.read_text(encoding="utf-8")
        )
        if OVERRIDES.exists()
        else {}
    )

    if not isinstance(overrides, dict):
        raise ValueError(
            "broadcast-overrides.json must be an object"
        )

    for game in unique.values():
        entry = overrides.get(game["id"], [])

        if isinstance(entry, dict):
            entry = entry.get("broadcasts", [])

        if not isinstance(entry, list):
            entry = []

        game["broadcasts"] = [
            item for item in entry
            if valid_override(item)
        ]

    xmltv_matches = 0

    try:
        xmltv_matches = load_xmltv(
            list(unique.values())
        )

    except Exception as exc:
        errors.append(f"XMLTV: {exc}")
        print(f"XMLTV warning: {exc}")

    output = {
        "updatedAt": (
            now.isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        ),
        "schemaVersion": 5,
        "source": (
            "ESPN fixtures; event-specific ESPN leads; "
            "optional XMLTV matches; manually verified overrides"
        ),
        "successfulChecks": (
            len(jobs)
            - len([
                error for error in errors
                if not error.startswith("XMLTV:")
            ])
        ),
        "totalChecks": len(jobs),
        "xmltvMatches": xmltv_matches,
        "errors": errors[:30],
        "items": sorted(
            unique.values(),
            key=lambda game: (
                game["start"], game["id"]
            ),
        ),
    }

    temporary = OUTPUT.with_suffix(".json.tmp")

    temporary.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    temporary.replace(OUTPUT)

    print(f"Saved {len(unique)} fixtures")
    print(
        f"Matched {xmltv_matches} "
        "XMLTV broadcaster listings"
    )
    print(f"Recorded {len(errors)} source errors")


if __name__ == "__main__":
    main()
