#!/usr/bin/env python3
"""Sports Almanac V11: automatic fixtures and UK/US viewing-source catalogue.

Free/no-key inputs: ESPN scoreboards, optional XMLTV_URL and manual overrides.
Rights-based rules are dated 2026-27 and deliberately separate confirmed
whole-league availability from possible/blackout-dependent viewing options.
The script cannot obtain private streaming-platform catalogues or deep links.
"""

import concurrent.futures
import datetime as dt
import difflib
import gzip
import io
import json
import os
import pathlib
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "sports-fixtures.json"
OVERRIDES = ROOT / "broadcast-overrides.json"
CHANNELS = ROOT / "xmltv-channels.json"
UTC = dt.timezone.utc
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")

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

# ESPN event-level broadcast leads. ESPN is an unofficial source and a lead
# is not verified streaming availability.
NETWORKS = {
    "ABC": "ABC", "CBS": "CBS", "FOX": "FOX", "NBC": "NBC",
    "ESPN": "ESPN", "ESPN2": "ESPN2", "ESPN+": "ESPN+",
    "ESPN SELECT": "ESPN+", "PEACOCK": "Peacock",
    "PRIME VIDEO": "Prime Video", "AMAZON PRIME VIDEO": "Prime Video",
    "AMAZON": "Prime Video", "NBA TV": "NBA TV", "TNT": "TNT",
    "TBS": "TBS", "FS1": "FS1", "FS2": "FS2",
    "PARAMOUNT+": "Paramount+", "APPLE TV": "Apple TV",
    "APPLE TV+": "Apple TV", "NETFLIX": "Netflix",
    "NFL NETWORK": "NFL Network", "MLB NETWORK": "MLB Network",
    "NHL NETWORK": "NHL Network", "USA NETWORK": "USA Network",
    "CBSSN": "CBS Sports Network", "CBS SPORTS NETWORK": "CBS Sports Network",
    "HBO MAX": "HBO Max", "FANDANGO": "Fandango",
    "YOUTUBE": "YouTube", "THE CW": "The CW",
}

UK_CHANNELS = {
    "sky sports": "Sky Sports", "tnt sports": "TNT Sports",
    "premier sports": "Premier Sports", "bbc one": "BBC iPlayer",
    "bbc two": "BBC iPlayer", "bbc three": "BBC iPlayer",
    "bbc four": "BBC iPlayer", "bbc1": "BBC iPlayer",
    "bbc2": "BBC iPlayer", "itv1": "ITVX", "itv2": "ITVX",
    "itv3": "ITVX", "itv4": "ITVX", "channel 4": "Channel 4",
    "channel 5": "Channel 5", "5action": "Channel 5",
    "5 action": "Channel 5", "five action": "Channel 5",
}

SOURCES = {
    "mls": "https://www.mlssoccer.com/how-to-watch/",
    "nba": "https://support.watch.nba.com/hc/en-us/articles/115002481154-League-Pass-Blackout-Guide",
    "wnba": "https://support.wnba.com/hc/en-us/articles/19679847275927-Blackouts",
    "mlb": "https://www.mlb.com/live-stream-games/",
    "nfl_uk": "https://www.dazn.com/en-EN/help/articles/16858954355485-nfl-game-pass-blackout-restrictions-in-the-uk-and-republic-of-ireland",
    "nfl_us": "https://support.nfl.com/hc/en-us/articles/40568374746644-How-to-access-LIVE-NFL-Regular-Season-games",
    "nfl_sunday": "https://support.google.com/youtube/answer/17594070",
    "nhl_uk": "https://www.dazn.com/en-GB/help/articles/29693674363549-nhltv-on-dazn",
    "nhl_blackout": "https://www.dazn.com/en-HR/help/articles/29693615472541-nhl-blackout-restrictions",
    "nhl_us": "https://www.nhl.com/info/how-to-watch-and-stream-nhl-games",
    "serie_uk": "https://dazngroup.com/press-room/dazn-renews-serie-a-rights-in-the-uk-ireland-for-the-2026-27-season/",
    "serie_us": "https://www.paramountplus.com/sneak-peak/how-to-watch-serie-a-on-paramount-plus/",
    "serie_misc": "https://football-italia.net/where-to-watch-serie-a-in-2026-27/",
    "laliga_uk": "https://www.laliga.com/en-BR/news/laliga-announces-landmark-broadcast-deals-with-premier-sports-and-disney-in-the-uk-and-ireland",
    "fox_one": "https://www.fox.com/sports/football/nfl",
    "laliga_us": "https://espnpressroom.com/press-release/espn-presents-the-2026-27-laliga-season-beginning-aug-15/",
    "ucl_us": "https://www.paramountplus.com/sneak-peak/uefa-champions-league-schedule/",
    "ucl_uk": "https://www.uefa.com/uefachampionsleague/news/0253-0d82037aaedd-f371c464f919-1000--where-to-watch-the-uefa-champions-league/",
    "uel": "https://www.uefa.com/uefaeuropaleague/news/028d-1ae6d62165d6-69b17b354deb-1000/",
    "uwcl_uk": "https://press.disney.co.uk/news/disneyplus-kicks-off-the-road-to-warsaw-with-every-uefa-womens-champions-league-match-streaming-live-from-22-september",
    "uwcl_us": "https://www.paramountplus.com/shows/uefa-womens-champions-league/",
    "bundesliga_us": "https://www.bundesliga.com/en/bundesliga/news/bundesliga-broadens-broadcast-accessibility-for-fans-in-us-with-new-deals-versants-usa-sports-nbcuniversals-telemundo-38268",
    "premier_uk": "https://www.premierleague.com/en/about/faq/broadcast",
    "premier_us": "https://www.peacocktv.com/sports/premier-league",
    "wsl": "https://www.wslfootball.com/news/the-2026-27-fixtures-are-out",
    "tnt_hbo": "https://help.hbomax.com/gb-en/Answer/Detail/000002560",
    "sky_now": "https://www.sky.com/hello-sky/tv/where-to-watch-premier-league-games",
    "mlb_apple": "https://www.mlb.com/news/friday-night-baseball-on-apple-tv-for-2026-mlb-season",
}

WATCH_PAGES = {
    "Apple TV": "https://tv.apple.com/sports",
    "NBA League Pass": "https://www.nba.com/games",
    "WNBA League Pass": "https://www.wnba.com/schedule",
    "MLB.TV": "https://www.mlb.com/live-stream-games/",
    "NFL Game Pass": "https://www.dazn.com/en-GB/",
    "NFL Sunday Ticket": "https://tv.youtube.com/",
    "NFL+": "https://www.nfl.com/plus/",
    "NHL.TV": "https://www.dazn.com/en-GB/",
    "ESPN+": "https://www.espn.com/watch/",
    "ESPN": "https://www.espn.com/watch/",
    "Paramount+": "https://www.paramountplus.com/sports/",
    "Peacock": "https://www.peacocktv.com/sports",
    "Prime Video": "https://www.amazon.com/gp/video/storefront/",
    "Disney+": "https://www.disneyplus.com/",
    "DAZN": "https://www.dazn.com/en-GB/home",
    "HBO Max": "https://www.hbomax.com/",
    "TNT Sports": "https://www.tntsports.co.uk/",
    "Sky Sports": "https://www.skysports.com/watch",
    "NOW": "https://www.nowtv.com/watch-sky-sports-online",
    "BBC iPlayer": "https://www.bbc.co.uk/iplayer",
    "ITVX": "https://www.itv.com/watch",
    "Channel 4": "https://www.channel4.com/",
    "Channel 5": "https://www.channel5.com/",
    "Netflix": "https://www.netflix.com/",
    "Fandango": "https://www.fandango.com/",
    "YouTube": "https://www.youtube.com/",
    "YouTube TV": "https://tv.youtube.com/",
    "FOX One": "https://www.fox.com/sports/football/nfl",
    "Hulu + Live TV": "https://www.hulu.com/live-tv",
    "Fubo": "https://www.fubo.tv/",
}


def utc_time(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def timestamp(value):
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def season_2026_27(game):
    """These rights are documented for the 2026-27 sporting season only."""
    when = utc_time(game["start"])
    return (when.year == 2026 and when.month >= 7) or (when.year == 2027 and when.month <= 6)


def season_2026_nfl(game):
    when = utc_time(game["start"])
    return (when.year == 2026 and when.month >= 8) or (when.year == 2027 and when.month <= 2)


def build_entry(country, service, source, note, verified=False, basis="competition-rights", **extra):
    entry = {
        "country": country,
        "service": service,
        "verified": verified,
        "basis": basis,
        "sourceUrl": source,
        "note": note,
    }
    if service in WATCH_PAGES:
        entry["watchUrl"] = WATCH_PAGES[service]  # Official landing page; not a game deep link.
    entry.update(extra)
    return entry


def add(game, entry):
    """Deduplicate with evidence priority; verified entries always win."""
    country, service = entry["country"], entry["service"]
    found = next((x for x in game["broadcasts"] if x.get("country") == country and x.get("service") == service), None)
    if found is not None:
        return False
    if entry["verified"]:
        game["broadcastLeads"] = [x for x in game["broadcastLeads"]
                                  if not (x.get("country") == country and x.get("service") == service)]
        game["broadcasts"].append(entry)
        return True
    priority = {"matched-tv-listing": 5, "event-schedule": 4,
                "network-simulcast": 3, "competition-rights": 2,
                "blackout-dependent-coverage": 1}
    for i, old in enumerate(game["broadcastLeads"]):
        if old.get("country") == country and old.get("service") == service:
            if priority.get(entry.get("basis"), 0) > priority.get(old.get("basis"), 0):
                game["broadcastLeads"][i] = entry
                return True
            return False
    game["broadcastLeads"].append(entry)
    return True


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "SportsAlmanac/3.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)


def team_name(competitor):
    team = competitor.get("team") or {}
    return team.get("displayName") or team.get("name") or "TBC"


def espn_leads(event, competition, url):
    names = []
    for obj in (competition, event):
        for item in obj.get("broadcasts", []) or []:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                names.extend(str(n) for n in item.get("names", []) or [] if n)
                if item.get("name"):
                    names.append(str(item["name"]))
        for item in obj.get("geoBroadcasts", []) or []:
            if isinstance(item, dict):
                media = item.get("media") or {}
                if isinstance(media, dict) and media.get("shortName"):
                    names.append(str(media["shortName"]))
    leads, seen = [], set()
    for raw in names:
        service = NETWORKS.get(raw.strip().upper())
        if service and service not in seen:
            leads.append(build_entry("US", service, url,
                                     "ESPN lists this network for this game; regional access and blackouts unverified.",
                                     basis="event-schedule"))
            seen.add(service)
    return leads


def fetch_day(job):
    sport, league, path, day = job
    params = urllib.parse.urlencode({"dates": day.strftime("%Y%m%d"), "limit": 300})
    url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?{params}"
    try:
        payload = get_json(url)
        if not isinstance(payload.get("events"), list):
            raise ValueError("Missing events array")
        games = []
        for event in payload["events"]:
            try:
                competition = event["competitions"][0]
                competitors = competition["competitors"]
                home = next(t for t in competitors if t.get("homeAway") == "home")
                away = next(t for t in competitors if t.get("homeAway") == "away")
                start = utc_time(event["date"])
                games.append({
                    "id": f"espn:{path}:{event['id']}",
                    "sport": sport, "competition": league,
                    "title": f"{team_name(away)} at {team_name(home)}",
                    "homeTeam": team_name(home), "awayTeam": team_name(away),
                    "start": timestamp(start),
                    "liveStatus": event.get("status", {}).get("type", {}).get("description", "Scheduled"),
                    "fixtureSource": url,
                    "broadcasts": [], "broadcastLeads": espn_leads(event, competition, url),
                })
            except (KeyError, IndexError, StopIteration, TypeError, ValueError, AttributeError):
                continue
        return games, None
    except Exception as exc:
        return [], f"{path} {day}: {exc}"


def put(game, country, service, source_key, note, verified=False, basis="competition-rights", **extra):
    return add(game, build_entry(country, service, SOURCES[source_key], note,
                                 verified, basis, **extra))


def add_official_rights(games):
    """Add season-bound, official whole-league and conditional service rights."""
    counts = Counter()
    for game in games:
        comp = game["competition"]
        when = utc_time(game["start"])
        is_2026_27 = season_2026_27(game)

        def rule(country, service, source, note, verified=False, basis="competition-rights", **extra):
            if put(game, country, service, source, note, verified, basis, **extra):
                counts[f"{country}: {service} ({'confirmed' if verified else 'possible'})"] += 1

        if comp == "MLS" and when.year == 2026:
            for country in ("UK", "US"):
                rule(country, "Apple TV", "mls", "Every 2026 MLS match is on Apple TV; no blackouts.", True,
                     "official-league-wide-coverage")

        elif comp == "NBA":
            rule("UK", "NBA League Pass", "nba", "Every NBA game is live on League Pass outside the US and Canada.",
                 True, "official-league-wide-coverage")
            rule("US", "NBA League Pass", "nba", "Out-of-market games only; local and national live blackouts vary by location.",
                 basis="blackout-dependent-coverage")

        elif comp == "WNBA" and when.year in (2026, 2027):
            rule("UK", "WNBA League Pass", "wnba", "All games available live outside the US and Canada in supported countries.",
                 True, "official-league-wide-coverage")
            rule("US", "WNBA League Pass", "wnba", "National and local live blackouts apply; check the game and ZIP code.",
                 basis="blackout-dependent-coverage")

        elif comp == "MLB":
            if when.year == 2026:
                rule("UK", "MLB.TV", "mlb", "Most MLB games are on MLB.TV; select exclusive games and postseason rules may prevent live viewing.",
                     basis="blackout-dependent-coverage")
                rule("US", "MLB.TV", "mlb", "Out-of-market and other restrictions apply; most postseason live streams need a participating TV provider.",
                     basis="blackout-dependent-coverage")
                if when.astimezone(NEW_YORK).weekday() == 4:
                    for country in ("UK", "US"):
                        rule(country, "Apple TV", "mlb_apple", "Selected Friday Night Baseball doubleheader games only; this fixture is not yet confirmed.")

        elif comp == "NFL" and season_2026_nfl(game):
            rule("UK", "NFL Game Pass", "nfl_uk", "On DAZN; two selected Sunday regular-season matches per week can be blacked out live.",
                 basis="blackout-dependent-coverage")
            rule("US", "NFL+", "nfl_us", "Live games on phones/tablets only when local or nationally televised in your market.",
                 basis="blackout-dependent-coverage")
            local = when.astimezone(NEW_YORK)
            if local.weekday() == 6 and 12 <= local.hour < 20:
                rule("US", "NFL Sunday Ticket", "nfl_sunday", "Only eligible out-of-market Sunday afternoon CBS/FOX games; local and national exclusions apply.",
                     basis="blackout-dependent-coverage")
            if local.month == 12 and local.day == 25 and local.year == 2026:
                rule("US", "Netflix", "nfl_us", "Selected Christmas NFL games stream on Netflix; not all December 25 fixtures.")

        elif comp == "NHL" and is_2026_27:
            rule("UK", "NHL.TV", "nhl_uk", "NHL.TV on DAZN; selected Premier Sports exclusives are blacked out live in the UK.",
                 basis="blackout-dependent-coverage")
            rule("US", "ESPN+", "nhl_us", "Many out-of-market NHL games, excluding local, national and NHL Network blackouts.",
                 basis="blackout-dependent-coverage")
            rule("UK", "Premier Sports", "nhl_blackout", "Selected NHL games only; check the Premier Sports listings.")

        elif comp == "Serie A" and is_2026_27:
            local = when.astimezone(LONDON)
            # UK 2026-27 3pm Saturday live-TV restriction can also delay nearby kickoffs.
            restricted = local.weekday() == 5 and 14 <= local.hour < 18
            rule("UK", "DAZN", "serie_uk", "All 2026-27 Serie A games are carried by DAZN, but Saturday afternoon live restrictions may delay coverage.",
                 not restricted, "official-league-wide-coverage" if not restricted else "blackout-dependent-coverage")
            rule("US", "Paramount+", "serie_us", "All 380 Serie A games live on Paramount+ in the US in 2026-27.",
                 True, "official-league-wide-coverage")
            rule("UK", "TNT Sports", "serie_misc", "Selected Serie A fixtures are shared with TNT Sports; check individual listing.")
            rule("UK", "HBO Max", "tnt_hbo", "TNT Sports add-on only, if this Serie A match is selected for TNT.")
            rule("UK", "BBC iPlayer", "serie_misc", "Selected free-to-air Serie A games only; individual fixture not confirmed.")

        elif comp == "La Liga" and is_2026_27:
            rule("US", "ESPN+", "laliga_us", "All 380 La Liga matches stream on ESPN+ in the US in 2026-27.",
                 True, "official-league-wide-coverage")
            rule("UK", "Premier Sports", "laliga_uk", "Premier Sports shows most UK La Liga fixtures; selected late Saturday matches are exclusive to Disney+.")
            rule("UK", "Disney+", "laliga_uk", "Exclusive UK late-Saturday La Liga fixture, if this match is the scheduled selection; otherwise not carried.")

        elif comp == "Bundesliga" and is_2026_27:
            rule("US", "Peacock", "bundesliga_us", "All 2026-27 Bundesliga fixtures stream in Spanish on Peacock in the US.",
                 True, "official-league-wide-coverage", language="Spanish")
            rule("US", "Fandango", "bundesliga_us", "Most Bundesliga matches stream free in English; some are instead on USA Network.",
                 basis="competition-rights", free=True, language="English")
            rule("US", "USA Network", "bundesliga_us", "At least 30 matches per season air on USA Network; check this fixture.")

        elif comp == "Champions League" and is_2026_27:
            rule("US", "Paramount+", "ucl_us", "Every UEFA Champions League match streams on Paramount+ in the US.",
                 True, "official-league-wide-coverage")
            rule("UK", "TNT Sports", "ucl_uk", "TNT Sports carries most UK games; the Tuesday first pick is on Prime Video.")
            rule("UK", "HBO Max", "tnt_hbo", "TNT Sports add-on; only when TNT has the live fixture.")
            rule("UK", "Prime Video", "ucl_uk", "Selected first-pick Tuesday matches only; check the individual fixture.")

        elif comp == "Europa League" and is_2026_27:
            rule("US", "Paramount+", "uel", "Official US UEFA Europa League streaming rights in 2026-27.",
                 True, "official-league-wide-coverage")
            rule("UK", "TNT Sports", "uel", "2026-27 UEFA Europa League live broadcaster in the UK.",
                 True, "official-league-wide-coverage")
            rule("UK", "HBO Max", "tnt_hbo", "Live TNT Sports requires the HBO Max TNT Sports plan or an eligible provider entitlement.",
                 True, "official-channel-simulcast")

        elif comp == "Women’s Champions League" and is_2026_27:
            rule("UK", "Disney+", "uwcl_uk", "Every 2026-27 Women's Champions League fixture is included with Disney+ in the UK.",
                 True, "official-league-wide-coverage")
            rule("US", "Paramount+", "uwcl_us", "Every Women's Champions League match streams on Paramount+ in the US.",
                 True, "official-league-wide-coverage")
            rule("UK", "BBC iPlayer", "uwcl_uk", "Only selected free BBC matches; check individual listings.")

        elif comp == "Premier League" and is_2026_27:
            rule("UK", "Sky Sports", "premier_uk", "A selection of UK live fixtures; not every Premier League game is televised.")
            rule("UK", "NOW", "sky_now", "Selected games live with a NOW Sports membership when shown on Sky Sports.")
            rule("UK", "TNT Sports", "premier_uk", "Selected live Premier League matches, not every fixture.")
            rule("UK", "HBO Max", "tnt_hbo", "TNT Sports add-on required; selected TNT matches only.")
            rule("US", "Peacock", "premier_us", "Selected live games and NBC simulcasts; USA Network games may be unavailable live.")
            rule("US", "USA Network", "premier_us", "Selected Premier League fixtures on USA Network.")
            rule("US", "NBC", "premier_us", "Selected Premier League matches on NBC.")

        elif comp == "WSL" and is_2026_27:
            rule("UK", "Sky Sports", "wsl", "Sky Sports shows most, but not all, WSL fixtures.")
            rule("UK", "NOW", "wsl", "Sky Sports WSL games may be streamed with a NOW Sports membership.")
            rule("UK", "BBC iPlayer", "wsl", "Selected free BBC WSL fixtures, not the whole league.")
            rule("UK", "YouTube", "wsl", "Selected free WSL fixtures only; check official channel.", free=True)

    print(f"Added {sum(counts.values())} country/service coverage records from season-bound rights rules")
    return counts


def add_network_streaming_leads(games):
    """Derive optional streaming simulcasts only from an event's ESPN-listed US network."""
    n = 0
    for game in games:
        networks = {x.get("service") for x in game["broadcastLeads"] if x.get("country") == "US" and x.get("basis") == "event-schedule"}
        comp = game["competition"]
        options = []
        if comp in ("NBA", "WNBA", "NFL"):
            if "NBC" in networks:
                options.append(("Peacock", "NBC", "NBC games often stream on Peacock; check the specific event and plan."))
            if "CBS" in networks and comp in ("WNBA", "NFL"):
                options.append(("Paramount+", "CBS", "CBS simulcast may be limited to the viewer's local CBS market."))
            if "FOX" in networks and comp == "NFL":
                options.append(("FOX One", "fox_one", "FOX One streams FOX NFL games only in your applicable market."))
            if "ESPN" in networks or "ABC" in networks:
                options.append(("ESPN", "ESPN", "ESPN streaming access may require a TV provider or ESPN plan."))
        if comp == "NHL" and ("TNT" in networks or "TBS" in networks):
            options.append(("HBO Max", "nhl_us", "NHL games on TNT/TBS can stream with the appropriate HBO Max sports access."))
        if comp == "Premier League" and "NBC" in networks:
            options.append(("Peacock", "premier_us", "Only select NBC simulcasts are on Peacock; check this game."))
        # Virtual multichannel TV subscriptions are not direct event rights.
        # Only attach as a possible route when an ESPN-reported US linear
        # channel appears, with market/plan eligibility still unknown.
        linear = {"ABC", "CBS", "FOX", "NBC", "ESPN", "ESPN2", "FS1", "FS2",
                  "USA Network", "CBS Sports Network", "NBA TV", "NFL Network",
                  "MLB Network", "NHL Network", "TNT", "TBS"}
        if networks & linear:
            options.append(("YouTube TV", "", "May carry the ESPN-listed linear network; channel, region and subscription package must be checked."))
            options.append(("Hulu + Live TV", "", "May carry the ESPN-listed linear network; channel, region and subscription package must be checked."))
            if not (networks & {"TNT", "TBS"}):
                options.append(("Fubo", "", "May carry the ESPN-listed linear network; channel, region and subscription package must be checked."))
        for service, source, note in options:
            src = SOURCES.get(source, game["fixtureSource"])
            if add(game, build_entry("US", service, src, note, basis="network-simulcast")):
                n += 1
    print(f"Added {n} event-network streaming leads")
    return n


def normalise(value):
    value = str(value).casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(w for w in value.split() if w not in {"fc", "afc", "cf", "the"})


def team_in_text(team, text):
    target, content = normalise(team), normalise(text)
    if not target or not content:
        return False
    if re.search(r"\b" + re.escape(target) + r"\b", content):
        return True
    if len(target) < 8 or len(target.split()) < 2:
        return False
    a, b = target.split(), content.split()
    return any(difflib.SequenceMatcher(None, target, " ".join(b[i:i + len(a)])).ratio() >= 0.92
               for i in range(max(0, len(b) - len(a) + 1)))


def xmltv_time(value):
    value = value.strip()
    if re.fullmatch(r"\d{14}", value):
        return dt.datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    return dt.datetime.strptime(value, "%Y%m%d%H%M%S %z").astimezone(UTC)


def discover_channels(root):
    channels = {}
    for node in root.findall("channel"):
        channel_id = node.get("id", "")
        for name_node in node.findall("display-name"):
            name = (name_node.text or "").strip().casefold()
            for prefix, service in UK_CHANNELS.items():
                if name.startswith(prefix):
                    channels[channel_id] = {"country": "UK", "service": service}
                    break
            if channel_id in channels:
                break
    print(f"Automatically identified {len(channels)} UK broadcaster channels")
    return channels


def load_xmltv(games):
    url = os.environ.get("XMLTV_URL", "").strip()
    if not url:
        print("XMLTV_URL not set; skipping TV listings")
        return 0
    manual = json.loads(CHANNELS.read_text(encoding="utf-8")) if CHANNELS.exists() else {}
    if not isinstance(manual, dict):
        raise ValueError("xmltv-channels.json must be a JSON object")

    req = urllib.request.Request(url, headers={"User-Agent": "SportsAlmanac/3.0"})
    with urllib.request.urlopen(req, timeout=40) as response:
        raw = response.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ValueError("XMLTV download exceeds 20 MB")
    if raw[:2] == b"\x1f\x8b":
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(30_000_001)
    if len(raw) > 30_000_000:
        raise ValueError("XMLTV decompressed data exceeds 30 MB")

    root = ET.fromstring(raw)
    channel_map = {**discover_channels(root), **manual}
    mapped = set(channel_map)
    by_day = {}
    for game in games:
        by_day.setdefault(utc_time(game["start"]).date(), []).append(game)
    matches = 0
    eligible_programmes = 0
    for programme in root.findall("programme"):
        channel_id = programme.get("channel", "")
        if channel_id not in mapped:
            continue
        channel = channel_map[channel_id]
        if not isinstance(channel, dict) or channel.get("country") not in ("UK", "US") or not channel.get("service"):
            continue
        try:
            start = xmltv_time(programme.attrib["start"])
        except (KeyError, ValueError):
            continue
        title = " ".join((x.text or "") for x in programme.findall("title"))
        desc = " ".join((x.text or "") for x in programme.findall("desc"))
        content = f"{title} {desc}"
        eligible_programmes += 1
        candidates = (by_day.get(start.date(), [])
                      + by_day.get((start - dt.timedelta(days=1)).date(), [])
                      + by_day.get((start + dt.timedelta(days=1)).date(), []))
        for game in candidates:
            difference = (start - utc_time(game["start"])).total_seconds()
            if not -14400 <= difference <= 1800:
                continue
            if not team_in_text(game["homeTeam"], content) or not team_in_text(game["awayTeam"], content):
                continue
            entry = build_entry(
                channel["country"], channel["service"], channel.get("sourceUrl") or url,
                "Both teams appear in an XMLTV schedule programme near kickoff; check live availability.",
                basis="matched-tv-listing", programmeTitle=title, programmeStart=timestamp(start),
                xmltvChannel=channel_id,
            )
            if add(game, entry):
                matches += 1
            if channel["country"] == "UK" and channel["service"] == "Sky Sports":
                add(game, build_entry("UK", "NOW", SOURCES["sky_now"],
                                      "This Sky Sports programme may be watched with a NOW Sports membership.",
                                      basis="network-simulcast"))
            if channel["country"] == "UK" and channel["service"] == "TNT Sports":
                add(game, build_entry("UK", "HBO Max", SOURCES["tnt_hbo"],
                                      "TNT Sports streams on HBO Max with the TNT Sports plan or eligible entitlement.",
                                      basis="network-simulcast"))
    print(f"Read {eligible_programmes} mapped-channel TV programmes")
    return matches


def valid_override(item):
    return (isinstance(item, dict) and item.get("country") in ("UK", "US")
            and isinstance(item.get("service"), str) and bool(item["service"].strip())
            and item.get("verified") is True and isinstance(item.get("sourceUrl"), str)
            and item["sourceUrl"].startswith("https://"))


def main():
    now = dt.datetime.now(UTC)
    jobs = [(sport, league, path, now.date() + dt.timedelta(days=i))
            for sport, league, path in LEAGUES for i in range(32)]
    all_games, errors = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        for games, error in executor.map(fetch_day, jobs):
            all_games.extend(games)
            if error:
                errors.append(error)
    unique = {}
    for game in all_games:
        if now <= utc_time(game["start"]) < now + dt.timedelta(days=30):
            unique[game["id"]] = game
    if not unique:
        raise RuntimeError("No future fixtures retrieved; existing JSON has not been changed")

    overrides = json.loads(OVERRIDES.read_text(encoding="utf-8")) if OVERRIDES.exists() else {}
    if not isinstance(overrides, dict):
        raise ValueError("broadcast-overrides.json must be a JSON object")
    for game in unique.values():
        overrides_for_game = overrides.get(game["id"], [])
        if isinstance(overrides_for_game, dict):
            overrides_for_game = overrides_for_game.get("broadcasts", [])
        if not isinstance(overrides_for_game, list):
            overrides_for_game = []
        for entry in overrides_for_game:
            if valid_override(entry):
                add(game, entry)

    games = list(unique.values())
    rule_counts = add_official_rights(games)
    network_count = add_network_streaming_leads(games)
    xmltv_matches = 0
    try:
        xmltv_matches = load_xmltv(games)
    except Exception as exc:
        errors.append(f"XMLTV: {exc}")
        print(f"XMLTV warning: {exc}")

    confirmed = {country: sum(any(x.get("country") == country for x in game["broadcasts"]) for game in games)
                 for country in ("UK", "US")}
    possible = {country: sum(any(x.get("country") == country for x in game["broadcastLeads"]) for game in games)
                for country in ("UK", "US")}
    output = {
        "updatedAt": timestamp(now),
        "schemaVersion": 5,
        "rightsRulesCheckedAsOf": "2026-11-04",
        "source": "ESPN fixture data, event-level ESPN leads, optional XMLTV and sourced 2026-27 viewing rules; manual verified overrides",
        "successfulChecks": len(jobs) - sum(not e.startswith("XMLTV:") for e in errors),
        "totalChecks": len(jobs),
        "xmltvMatches": xmltv_matches,
        "networkStreamingLeads": network_count,
        "officialRightsEntries": sum(rule_counts.values()),
        "verifiedGamesByCountry": confirmed,
        "possibleGamesByCountry": possible,
        "errors": errors[:30],
        "items": sorted(games, key=lambda game: (game["start"], game["id"])),
    }
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT)

    print(f"Saved {len(games)} fixtures")
    print(f"Matched {xmltv_matches} XMLTV broadcaster listings")
    print(f"Added {network_count} event-network streaming leads")
    print(f"Verified game coverage: UK={confirmed['UK']}, US={confirmed['US']}")
    print(f"Possible/conditional coverage: UK={possible['UK']}, US={possible['US']}")
    print(f"Recorded {len(errors)} source errors")


if __name__ == "__main__":
    main()
