#!/usr/bin/env python3
"""Sports Almanac V13: automatic fixtures and UK/US viewing-source catalogue.

Free/no-key inputs: ESPN scoreboards, optional XMLTV_URL and manual overrides.
Rights-based rules are dated 2026-27 and deliberately separate confirmed
whole-league availability from possible/blackout-dependent viewing options.
The script cannot obtain private streaming-platform catalogues or deep links.
"""

import concurrent.futures
import datetime as dt
import difflib
import gzip
import html
import io
import json
import os
import pathlib
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from html.parser import HTMLParser
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
    "NBCSN": "NBCSN", "NBC SPORTS NETWORK": "NBCSN", "ESPN UNLIMITED": "ESPN",
    "PRIME": "Prime Video", "AMAZON PRIME": "Prime Video",
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
    "prime_ucl_schedule": "https://www.aboutamazon.co.uk/news/entertainment/whats-on-prime-video-uk-november-2026",
    "prime_ucl_rights": "https://www.aboutamazon.co.uk/news/entertainment/champions-league-prime-video-uk-renewal",
    "nfl_5_guide": "https://tvradar.uk/nfl-on-tv",
    "nba_nbc": "https://www.nba.com/news/every-nba-game-on-nbc-and-peacock-in-2026-27",
    "nba_espn": "https://www.nba.com/news/every-nba-game-on-abc-espn-in-2026-27",
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
    "NBCSN": "https://www.peacocktv.com/sports/nba",
    "Paramount+": "https://www.paramountplus.com/sports/",
    "Peacock": "https://www.peacocktv.com/sports",
    "Prime Video": "https://www.primevideo.com/salp/ucl-help/",
    "Prime Video PPV": "https://www.primevideo.com/",
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
    "FIFA+": "https://www.plus.fifa.com/",
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


# An exact Amazon-confirmed selection, not a guess about which English
# club gets the Tuesday broadcast. Other dates remain unknown until named.
PRIME_UCL_PICKS = (
    ("2026-11-03", "Manchester United", "Roma"),
    ("2026-11-24", "Arsenal", "Borussia Dortmund"),
)
PRIME_CONFIRMED_DATES = {dt.date.fromisoformat(day) for day, _, _ in PRIME_UCL_PICKS}
# The public Amazon schedule also names these broadcast dates but not yet
# the selected fixture. It includes a Wednesday final-round matchday.
PRIME_PENDING_DATES = {
    dt.date.fromisoformat(day) for day in (
        "2026-12-08", "2027-01-19", "2027-01-27", "2027-02-16",
        "2027-02-23", "2027-03-09", "2027-03-16", "2027-04-06",
        "2027-04-13",
    )
}


def team_equivalent(actual, listed):
    """Use conservative club aliases; do not treat every club from one city as equal."""
    aliases = {
        "man utd": "manchester united", "man united": "manchester united",
        "man city": "manchester city", "spurs": "tottenham hotspur",
        "tottenham": "tottenham hotspur", "borussia dortmund": "dortmund",
        "bvb": "dortmund", "vfb stuttgart": "stuttgart",
        "rb leipzig": "leipzig", "red bull leipzig": "leipzig",
        "paris saint germain": "psg", "paris st germain": "psg",
        "inter milan": "inter", "internazionale": "inter",
        "ac milan": "milan", "athletic club": "athletic bilbao",
        "atletico madrid": "atletico madrid",
        "bayern munich": "bayern munich", "fc bayern munich": "bayern munich",
        "psv eindhoven": "psv", "porto": "porto", "fc porto": "porto",
        "club brugge": "brugge", "brighton and hove albion": "brighton",
        "afc bournemouth": "bournemouth", "wolves": "wolverhampton wanderers",
        "west ham united": "west ham", "newcastle united": "newcastle",
        "nottingham forest": "nottingham forest", "aston villa": "aston villa",
        "arsenal women": "arsenal", "chelsea women": "chelsea",
        "liverpool women": "liverpool", "manchester city women": "manchester city",
        "manchester united women": "manchester united",
    }
    def canonical(value):
        words = normalise(value)
        words = re.sub(r"\b(women|ladies)\b", "", words).strip()
        return aliases.get(words, words)
    a, b = canonical(actual), canonical(listed)
    if a == b and a:
        return True
    # Single-word clubs can be compared as whole words (never substrings).
    if len(a) >= 4 and (re.search(r"\b" + re.escape(a) + r"\b", b) or
                        re.search(r"\b" + re.escape(b) + r"\b", a)):
        return True
    return bool(a and b and len(a) >= 9 and len(b) >= 9 and
                difflib.SequenceMatcher(None, a, b).ratio() >= 0.91)


def get_prime_first_pick(game):
    if game.get("competition") != "Champions League":
        return False
    local = utc_time(game["start"]).astimezone(LONDON)
    for day, home, away in PRIME_UCL_PICKS:
        if local.date().isoformat() != day:
            continue
        if ((team_equivalent(game["homeTeam"], home) and team_equivalent(game["awayTeam"], away)) or
            (team_equivalent(game["homeTeam"], away) and team_equivalent(game["awayTeam"], home))):
            return True
    return False


# Confirmed individual free-to-air NFL selections. Never assume every NFL
# Sunday 18:00 or 21:25 game is shown on Channel 5.
UK_NFL_ON_FIVE = (
    ("2026-11-08", "New York Jets", "Kansas City Chiefs"),
    ("2026-11-08", "Green Bay Packers", "New England Patriots"),
)


def add_confirmed_uk_nfl(games):
    n = 0
    for game in games:
        if game.get("competition") != "NFL":
            continue
        date = utc_time(game["start"]).astimezone(LONDON).date().isoformat()
        for day, away, home in UK_NFL_ON_FIVE:
            if day != date:
                continue
            if (team_equivalent(game["awayTeam"], away) and
                    team_equivalent(game["homeTeam"], home)):
                if put(game, "UK", "Channel 5", "nfl_5_guide",
                       "This exact NFL game is listed live and free on 5/5Action.",
                       True, "official-event-schedule"):
                    n += 1
    print(f"Added {n} specifically confirmed free Channel 5 NFL broadcasts")
    return n


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
            restricted = local.weekday() == 5 and dt.time(14, 45) <= local.time() < dt.time(17, 15)
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
            # Tuesday's Prime selection cannot be guessed from the kick-off time.
            # Once that day's first pick is individually identified, all the
            # OTHER games that day are the TNT/HBO Max matches.
            local = when.astimezone(LONDON)
            first_pick = get_prime_first_pick(game)
            prime_date = local.date() in PRIME_CONFIRMED_DATES
            if first_pick:
                rule("UK", "Prime Video", "prime_ucl_schedule",
                     "Amazon explicitly lists this individual UEFA Champions League match for Prime Video UK.",
                     True, "official-event-schedule")
            elif (local.weekday() != 1 and local.date() not in PRIME_PENDING_DATES) or prime_date:
                rule("UK", "TNT Sports", "ucl_uk",
                     "This is not the Prime Tuesday first pick; UEFA's UK remainder is carried by TNT Sports/HBO Max.",
                     True, "official-exclusive-remainder")
                rule("UK", "HBO Max", "tnt_hbo",
                     "TNT Sports live rights require the appropriate HBO Max sports entitlement.",
                     True, "official-channel-simulcast")
            else:
                rule("UK", "TNT Sports", "ucl_uk",
                     "Most Champions League games are on TNT, but the Prime Tuesday first pick is not yet identified.")
                rule("UK", "HBO Max", "tnt_hbo",
                     "Only if TNT holds this fixture; Tuesday Prime selection is not yet identified.")

        elif comp == "Europa League" and is_2026_27:
            rule("US", "Paramount+", "uel", "Official US UEFA Europa League streaming rights in 2026-27.",
                 True, "official-league-wide-coverage")
            rule("UK", "HBO Max", "tnt_hbo", "Every Europa League fixture streams through HBO Max with the sports entitlement.",
                 True, "official-league-wide-coverage")
            rule("UK", "TNT Sports", "uel", "Some Europa League matches are HBO Max-only; verify a linear TNT channel for this game.")

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

        elif comp == "UEFA Nations League" and is_2026_27:
            rule("UK", "ITVX", "wsl", "Selected England and European national-team matches; requires fixture-specific ITV listing.")
            rule("UK", "BBC iPlayer", "wsl", "Selected national-team matches only; check an individual BBC listing.")

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
            if "NBC" in networks or "NBCSN" in networks:
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


# A second no-key feed is used for UK event-level channels. It supplements
# XMLTV, which often contains only a few days of programme metadata.
# This is a third-party public TV guide, so matched listings remain leads,
# not verified game broadcasts. In particular, a Prime Video PPV label is
# NEVER treated as an ordinary Prime subscription match.
FOOTBALL_GUIDES = (
    "https://www.live-footballontv.com/",
    "https://www.live-footballontv.com/live-premier-league-football-on-tv.html",
    "https://www.live-footballontv.com/live-champions-league-football-on-tv.html",
    "https://www.live-footballontv.com/live-uefa-europa-league-football-on-tv.html",
    "https://www.live-footballontv.com/live-womens-football-on-tv.html",
    "https://www.live-footballontv.com/live-spanish-football-on-tv.html",
    "https://www.live-footballontv.com/live-italian-football-on-tv.html",
    "https://www.live-footballontv.com/live-german-football-on-tv.html",
    "https://www.live-footballontv.com/live-mls-football-on-tv.html",
    "https://www.live-footballontv.com/live-international-football-on-tv.html",
)
GUIDE_COMPETITIONS = {
    "UEFA Champions League": "Champions League",
    "UEFA Europa League": "Europa League",
    "Women's Champions League": "Women’s Champions League",
    "Women's Super League": "WSL",
    "Premier League": "Premier League",
    "La Liga": "La Liga",
    "Serie A": "Serie A",
    "Bundesliga": "Bundesliga",
    "MLS": "MLS",
    "UEFA Nations League": "UEFA Nations League",
}
GUIDE_DAY_RE = re.compile(
    r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(20\d{2})$", re.I)
GUIDE_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
GUIDE_MATCH_RE = re.compile(r"^(.{2,85}?)\s+v(?:s\.?)?\s+(.{2,85})$", re.I)


class GuideText(HTMLParser):
    """Extract readable lines without installing HTML scraping libraries."""
    BREAKS = {"div", "p", "li", "tr", "h1", "h2", "h3", "h4", "br", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in self.BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        if tag in self.BREAKS:
            self.parts.append("\n")

    def handle_data(self, value):
        if not self.skip:
            self.parts.append(value + " ")

    def lines(self):
        return [" ".join(part.split()) for part in "".join(self.parts).splitlines()
                if part.strip()]


def guide_channels(text):
    """Map literal channel labels only, not general statements about rights."""
    text = " ".join(text.split())
    lowered = text.casefold()
    names = []
    if "amazon prime ppv" in lowered or "prime video ppv" in lowered:
        names.append("Prime Video PPV")
    elif "amazon prime video" in lowered or re.search(r"\bprime video\b", lowered):
        names.append("Prime Video")
    for phrase, service in (
        ("sky sports", "Sky Sports"), ("tnt sports", "TNT Sports"),
        ("hbo max", "HBO Max"), ("premier sports", "Premier Sports"),
        ("laligatv", "LaLigaTV"), ("disney+", "Disney+"),
        ("dazn", "DAZN"), ("bbc iplayer", "BBC iPlayer"),
        ("bbc one", "BBC iPlayer"), ("bbc two", "BBC iPlayer"),
        ("bbc three", "BBC iPlayer"), ("bbc red button", "BBC iPlayer"),
        ("itvx", "ITVX"), ("itv1", "ITVX"),
        ("itv2", "ITVX"), ("itv3", "ITVX"), ("itv4", "ITVX"),
        ("channel 4", "Channel 4"), ("channel 5", "Channel 5"),
        ("apple tv", "Apple TV"), ("netflix", "Netflix"),
        ("wsl youtube", "YouTube"), ("bundesliga youtube", "YouTube"),
        ("premier player", "Premier Sports"), ("fifa+", "FIFA+"),
    ):
        if phrase in lowered:
            names.append(service)
    return list(dict.fromkeys(names))


def guide_competition(label):
    value = " ".join(label.casefold().replace("’", "'").split())
    if ("women's super league 2" in value or "wsl2" in value or
        "bundesliga 2" in value or "la liga 2" in value or "laliga 2" in value):
        return None
    if "women's champions league" in value:
        return "Women’s Champions League"
    if "champions league" in value:
        return "Champions League" if "uefa" in value else None
    if "europa league" in value:
        return "Europa League"
    for text, competition in GUIDE_COMPETITIONS.items():
        if text.casefold() in value:
            return competition
    return None


def parse_football_guide(page):
    """Parse listings only when date, kickoff, two clubs, league, channels align.

    Yields (UK-local kickoff, competition, first club, second club, services).
    Never infer a broadcaster just from the site-wide description.
    """
    parser = GuideText()
    parser.feed(page)
    lines = parser.lines()
    day = None
    fixtures = []
    for i, line in enumerate(lines):
        match_day = GUIDE_DAY_RE.fullmatch(line)
        if match_day:
            try:
                day = dt.date(int(match_day[3]), dt.datetime.strptime(match_day[2], "%B").month, int(match_day[1]))
            except ValueError:
                day = None
            continue
        clock = GUIDE_TIME_RE.fullmatch(line)
        if not clock or day is None:
            continue
        kickoff = dt.datetime.combine(day, dt.time(int(clock[1]), int(clock[2])), tzinfo=LONDON)
        # The next line should name two clubs; the following one should name
        # the actual competition, then an explicitly named broadcast service.
        for j in range(i + 1, min(i + 5, len(lines))):
            clubs = GUIDE_MATCH_RE.fullmatch(lines[j])
            if not clubs:
                if GUIDE_TIME_RE.fullmatch(lines[j]) or GUIDE_DAY_RE.fullmatch(lines[j]):
                    break
                continue
            for k in range(j + 1, min(j + 5, len(lines))):
                comp = guide_competition(lines[k])
                if comp:
                    collected = []
                    for next_line in lines[k + 1: min(k + 6, len(lines))]:
                        if (GUIDE_TIME_RE.fullmatch(next_line) or
                            GUIDE_DAY_RE.fullmatch(next_line) or
                            GUIDE_MATCH_RE.fullmatch(next_line)):
                            break
                        collected.append(next_line)
                    channels = guide_channels(" ".join(collected))
                    if channels:
                        fixtures.append((kickoff.astimezone(UTC), comp,
                                         clubs[1].strip(), clubs[2].strip(), channels))
                    break
            break
    return fixtures


def load_uk_football_listings(games):
    """Optional best-effort 30-day UK broadcast fixture schedule matching."""
    index = {}
    for game in games:
        if game["sport"] != "Football":
            continue
        day = utc_time(game["start"]).astimezone(LONDON).date()
        index.setdefault((day, game["competition"]), []).append(game)
    matches, errors = 0, []
    for source in FOOTBALL_GUIDES:
        try:
            request = urllib.request.Request(source, headers={
                "User-Agent": "Mozilla/5.0 (compatible; SportsAlmanac/3.1; +https://github.com/samgipple-oss/SPORTS-ALMANAC)",
                "Accept": "text/html",
            })
            with urllib.request.urlopen(request, timeout=16) as response:
                raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ValueError("HTML exceeds 4 MB")
            listings = parse_football_guide(raw.decode("utf-8", "replace"))
            for kickoff, comp, left, right, services in listings:
                for game in index.get((kickoff.astimezone(LONDON).date(), comp), []):
                    if abs((utc_time(game["start"]) - kickoff).total_seconds()) > 40 * 60:
                        continue
                    clubs_match = (
                        (team_equivalent(game["homeTeam"], left) and team_equivalent(game["awayTeam"], right)) or
                        (team_equivalent(game["homeTeam"], right) and team_equivalent(game["awayTeam"], left))
                    )
                    if not clubs_match:
                        continue
                    for service in services:
                        # Only the exact official Amazon Prime selected match is
                        # verified; other third-party channel entries are leads.
                        if comp == "Champions League" and service == "Prime Video" and not get_prime_first_pick(game):
                            note = "A TV guide lists Prime; verify against Amazon's first-pick schedule."
                        elif service == "Prime Video PPV":
                            note = "Separate pay-per-view purchase required; NOT included in ordinary Prime Video."
                        else:
                            note = "Individual teams, local date and kickoff matched a published UK TV fixture guide; check provider availability."
                        if add(game, build_entry("UK", service, source, note,
                                                 basis="matched-tv-listing",
                                                 programmeTitle=f"{left} v {right}",
                                                 programmeStart=timestamp(kickoff))):
                            matches += 1
                        if service == "Sky Sports":
                            add(game, build_entry("UK", "NOW", source,
                                                  "This identified Sky Sports match may be viewed with eligible NOW Sports access.",
                                                  basis="network-simulcast"))
            print(f"Football guide: {len(listings)} listed matches checked from {source}")
        except Exception as exc:
            errors.append(f"Football guide {source}: {exc}")
            print(f"Football guide warning: {source}: {exc}")
    print(f"Matched {matches} individual UK football broadcast listings")
    return matches, errors


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




# NBA publishes its selected US national games for the full season. We match
# DATE, TEAMS and (when supplied) scheduled start, rather than assuming a game
# is on Peacock/ESPN because it happens on the usual broadcasting weekday.
NBA_OFFICIAL_US_SCHEDULES = (
    (SOURCES["nba_nbc"], "Peacock"),
    (SOURCES["nba_espn"], "ESPN"),
)
NBA_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
              "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
NBA_MATCH_LINE = re.compile(
    r"\b(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+"
    r"(?P<day>\d{1,2}):?\s*(?P<away>[^—\n]{2,55}?)\s+"
    r"(?:vs\.?|at)\s+(?P<home>[^—\n]{2,55}?)\s*[—–-]\s*"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[ap]\.?m\.?)\s*ET",
    flags=re.I,
)


def parse_nba_official_games(raw):
    parser = GuideText()
    parser.feed(raw)
    text = "\n".join(parser.lines())
    records = []
    for match in NBA_MATCH_LINE.finditer(text):
        month = NBA_MONTHS[match["month"].lower()[:3]]
        year = 2026 if month >= 7 else 2027
        try:
            day = dt.date(year, month, int(match["day"]))
            hour = int(match["hour"]) % 12 + (12 if match["ampm"].lower().startswith("p") else 0)
            minute = int(match["minute"] or 0)
            when = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=NEW_YORK).astimezone(UTC)
        except ValueError:
            continue
        records.append((when, match["away"].strip(), match["home"].strip(),
                        text[match.end(): match.end() + 35].split("\n", 1)[0]))
    return records


def load_nba_official_national_games(games):
    by_day = {}
    for game in games:
        if game["competition"] == "NBA":
            date = utc_time(game["start"]).astimezone(NEW_YORK).date()
            by_day.setdefault(date, []).append(game)
    matches = 0
    warnings = []
    for source, default_service in NBA_OFFICIAL_US_SCHEDULES:
        try:
            request = urllib.request.Request(source, headers={
                "User-Agent": "Mozilla/5.0 SportsAlmanac/4.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=18) as response:
                html_text = response.read(3_000_001)
            if len(html_text) > 3_000_000:
                raise ValueError("NBA schedule exceeds 3 MB")
            listings = parse_nba_official_games(html_text.decode("utf-8", "replace"))
            for when, away, home, suffix in listings:
                candidates = by_day.get(when.astimezone(NEW_YORK).date(), [])
                for game in candidates:
                    if abs((utc_time(game["start"]) - when).total_seconds()) > 40 * 60:
                        continue
                    if not ((team_equivalent(game["homeTeam"], home) and team_equivalent(game["awayTeam"], away)) or
                            (team_equivalent(game["homeTeam"], away) and team_equivalent(game["awayTeam"], home))):
                        continue
                    service = default_service
                    # ABC-identified games are still available via ESPN's app;
                    # add the actual linear channel when the page explicitly says ABC.
                    if default_service == "ESPN" and re.search(r"\bABC\b", suffix, re.I):
                        if add(game, build_entry("US", "ABC", source,
                             "This game is on NBA's official ABC national broadcast schedule.",
                             True, "official-event-schedule")):
                            matches += 1
                    if add(game, build_entry("US", service, source,
                           "Individual teams, tip-off and date match NBA's official 2026-27 national broadcast schedule.",
                           True, "official-event-schedule")):
                        matches += 1
                    break
            print(f"NBA official national schedule: {len(listings)} candidate listings from {source}")
        except Exception as exc:
            warnings.append(f"{source}: {exc}")
            print(f"NBA national schedule warning: {source}: {exc}")
    print(f"Matched {matches} NBA official US game broadcast entries")
    return matches, warnings

# NHL publishes a first-party list of UK blackouts. We treat an exact match
# as a confirmed Premier Sports selection and never label that game's NHL.TV
# access as live. Unlisted games remain conditional because the public list
# can be incomplete, delayed or changed without notice.
class RightsTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.cell_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
            self.cell_depth = 1
        elif self.cell is not None:
            self.cell_depth += 1

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.row is not None and self.cell is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
            self.cell_depth = 0
        elif tag == "tr" and self.row is not None:
            if len(self.row) >= 4:
                self.rows.append(self.row)
            self.row = None
        elif self.cell is not None:
            self.cell_depth = max(self.cell_depth - 1, 0)


def parse_nhl_blackouts(content):
    parser = RightsTableParser()
    parser.feed(content)
    records = []
    for row in parser.rows:
        day_text, time_text, matchup, countries = row[:4]
        if not re.search(r"\bUK\b|Ireland", countries, re.I):
            continue
        match = re.split(r"\s+(?:vs\.?|v)\s+", matchup, maxsplit=1, flags=re.I)
        if len(match) != 2:
            continue
        day = None
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d %B %Y", "%d %b %Y", "%dth %B %Y"):
            try:
                day = dt.datetime.strptime(day_text.strip(), fmt).date()
                break
            except ValueError:
                continue
        if day is None:
            # Some DAZN pages omit the year or use ordinal dates (e.g. 5th November).
            v = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", day_text, flags=re.I)
            for fmt in ("%d %B %Y", "%d %b %Y"):
                try:
                    day = dt.datetime.strptime(v, fmt).date()
                    break
                except ValueError:
                    pass
        if day is None:
            continue
        try:
            clock = dt.datetime.strptime(time_text.upper().replace(".", ""), "%I:%M %p").time()
        except ValueError:
            continue
        local = dt.datetime.combine(day, clock, tzinfo=NEW_YORK)
        records.append((local.astimezone(UTC), match[0].strip(), match[1].strip()))
    return records


def load_nhl_official_blackouts(games):
    source = SOURCES["nhl_blackout"]
    request = urllib.request.Request(source, headers={"User-Agent": "Mozilla/5.0 SportsAlmanac/4.0", "Accept": "text/html"})
    try:
        with urllib.request.urlopen(request, timeout=18) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("NHL blackout page exceeds 2 MB")
        records = parse_nhl_blackouts(data.decode("utf-8", "replace"))
        matched = 0
        for game in games:
            if game["competition"] != "NHL":
                continue
            start = utc_time(game["start"])
            for when, left, right in records:
                if abs((start - when).total_seconds()) > 60 * 60:
                    continue
                if not ((team_equivalent(game["homeTeam"], left) and team_equivalent(game["awayTeam"], right)) or
                        (team_equivalent(game["homeTeam"], right) and team_equivalent(game["awayTeam"], left))):
                    continue
                game["broadcastLeads"] = [entry for entry in game["broadcastLeads"]
                        if not (entry.get("country") == "UK" and entry.get("service") == "NHL.TV")]
                if put(game, "UK", "Premier Sports", "nhl_blackout",
                       "DAZN officially lists this specific fixture as blacked out from UK NHL.TV; UK live rights belong to Premier Sports.",
                       True, "official-event-schedule"):
                    matched += 1
                break
        print(f"NHL official blackout table: {len(records)} UK records, {matched} exact fixture matches")
        return matched, None
    except Exception as exc:
        print(f"NHL official blackout source warning: {exc}")
        return 0, str(exc)


def coverage_audit(games):
    """Unique fixture coverage; possible/confirmed counts can overlap."""
    report = {}
    for competition in sorted(set(g["competition"] for g in games)):
        subgroup = [g for g in games if g["competition"] == competition]
        row = {"fixtures": len(subgroup)}
        for country in ("UK", "US"):
            confirmed = sum(any(x.get("country") == country for x in g["broadcasts"]) for g in subgroup)
            tentative = sum(any(x.get("country") == country for x in g["broadcastLeads"]) for g in subgroup)
            combined = sum(any(x.get("country") == country for x in g["broadcasts"] + g["broadcastLeads"]) for g in subgroup)
            event_specific = sum(any(x.get("country") == country and
                     x.get("basis") in ("matched-tv-listing", "event-schedule", "official-event-schedule", "official-exclusive-remainder")
                     for x in g["broadcasts"] + g["broadcastLeads"]) for g in subgroup)
            row[country] = {"confirmedFixtures": confirmed, "possibleFixtures": tentative,
                            "anyCoverageFixtures": combined, "uncoveredFixtures": len(subgroup) - combined,
                            "eventSpecificFixtures": event_specific,
                            "confirmedPct": round(100 * confirmed / len(subgroup), 1),
                            "anyCoveragePct": round(100 * combined / len(subgroup), 1)}
        report[competition] = row
    return report

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
    scoreboard_error_count = len(errors)
    rule_counts = add_official_rights(games)
    nfl_five_count = add_confirmed_uk_nfl(games)
    network_count = add_network_streaming_leads(games)
    football_matches, football_errors = load_uk_football_listings(games)
    errors.extend(football_errors)
    nhl_matches, nhl_warning = load_nhl_official_blackouts(games)
    nba_matches, nba_warnings = load_nba_official_national_games(games)
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
    audit = coverage_audit(games)
    any_country = {country: sum(any(x.get("country") == country for x in g["broadcasts"] + g["broadcastLeads"]) for g in games)
                   for country in ("UK", "US")}
    event_country = {country: sum(any(x.get("country") == country and
                        x.get("basis") in ("matched-tv-listing", "event-schedule", "official-event-schedule", "official-exclusive-remainder")
                        for x in g["broadcasts"] + g["broadcastLeads"]) for g in games)
                     for country in ("UK", "US")}
    output = {
        "updatedAt": timestamp(now),
        "schemaVersion": 5,
        "rightsRulesCheckedAsOf": "2026-11-04",
        "source": "ESPN fixtures and US event listings, UK football guides, optional XMLTV, NHL official UK blackout listings, rights rules, verified manual overrides",
        "broadcastAuditVersion": 1,
        "coverageByCompetition": audit,
        "anyCoverageGamesByCountry": any_country,
        "eventSpecificGamesByCountry": event_country,
        "officialNHLBlackoutFixtureMatches": nhl_matches,
        "nbaOfficialUSNationalBroadcastEntries": nba_matches,
        "nbaOfficialSourceWarnings": nba_warnings,
        "nhlBlackoutSourceWarning": nhl_warning,
        "successfulChecks": len(jobs) - scoreboard_error_count,
        "totalChecks": len(jobs),
        "xmltvMatches": xmltv_matches,
        "footballTVListingMatches": football_matches,
        "specificNFLFreeBroadcasts": nfl_five_count,
        "footballTVListingSourceErrors": len(football_errors),
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
    print(f"Matched {football_matches} individual UK football viewing listings")
    print(f"Added {network_count} event-network streaming leads")
    print(f"Verified game coverage: UK={confirmed['UK']}, US={confirmed['US']}")
    print(f"Possible/conditional coverage: UK={possible['UK']}, US={possible['US']}")
    print(f"Any broadcast coverage (verified OR possible): UK={any_country['UK']}/{len(games)}, US={any_country['US']}/{len(games)}")
    print(f"Event-specific broadcaster evidence: UK={event_country['UK']}/{len(games)}, US={event_country['US']}/{len(games)}")
    print(f"Official NHL UK blackout matches: {nhl_matches}")
    print(f"Official NBA US national broadcast entries: {nba_matches}")
    print("Uncovered fixtures by competition (UK / US):")
    for league, row in audit.items():
        print(f"  {league}: {row['UK']['uncoveredFixtures']} / {row['US']['uncoveredFixtures']} (of {row['fixtures']})")
    print(f"Recorded {len(errors)} source errors")


if __name__ == "__main__":
    main()
