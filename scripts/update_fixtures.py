#!/usr/bin/env python3
"""Build a 30-day UTC fixture feed. ESPN is unofficial; monitor coverage."""
import concurrent.futures as cf
import datetime as dt
import json
import pathlib
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'sports-fixtures.json'
OVERRIDES = ROOT / 'broadcast-overrides.json'
LEAGUES = [
 ('Basketball','NBA','basketball/nba'),
 ('Basketball','WNBA','basketball/wnba'),
 ('Baseball','MLB','baseball/mlb'),
 ('American football','NFL','football/nfl'),
 ('Ice hockey','NHL','hockey/nhl'),
 ('Football','Premier League','soccer/eng.1'),
 ('Football','Champions League','soccer/uefa.champions'),
 ('Football','Europa League','soccer/uefa.europa'),
 ('Football','MLS','soccer/usa.1'),
 ('Football','La Liga','soccer/esp.1'),
 ('Football','Bundesliga','soccer/ger.1'),
 ('Football','Serie A','soccer/ita.1'),
 ('Football','WSL','soccer/eng.w.1'),
 ('Football','Women’s Champions League','soccer/uefa.wchampions'),
 ('Football','UEFA Nations League','soccer/uefa.nations'),
]


# ESPN sometimes provides US network listings. These are useful leads, NOT
# verified subscription entitlements, UK listings, or blackout guarantees.
NETWORKS = {'ABC':'ABC','CBS':'CBS','FOX':'FOX','NBC':'NBC','ESPN':'ESPN',
            'ESPN2':'ESPN','ESPN+':'ESPN+','PEACOCK':'Peacock',
            'PRIME VIDEO':'Prime Video','AMAZON PRIME VIDEO':'Prime Video',
            'NBA TV':'NBA TV','TNT':'TNT','TBS':'TBS','FS1':'FS1',
            'NFL NETWORK':'NFL Network','MLB NETWORK':'MLB Network',
            'NHL NETWORK':'NHL Network','USA NETWORK':'USA Network',
            'PARAMOUNT+':'Paramount+','APPLE TV':'Apple TV'}

def espn_broadcast_leads(event, competition, url):
    names=[]
    for obj in (competition,event):
        for b in obj.get('broadcasts',[]) or []:
            if isinstance(b,str): names.append(b)
            elif isinstance(b,dict):
                names.extend(str(n) for n in (b.get('names') or []) if n)
                if b.get('name'): names.append(str(b['name']))
        for b in obj.get('geoBroadcasts',[]) or []:
            if isinstance(b,dict):
                media=b.get('media') or {}
                if isinstance(media,dict) and media.get('shortName'): names.append(str(media['shortName']))
    leads=[];seen=set()
    for raw in names:
        key=raw.strip().upper()
        service=NETWORKS.get(key)
        if service and service not in seen:
            leads.append({'country':'US','service':service,'verified':False,
                          'sourceUrl':url,'note':'ESPN schedule listing; coverage and blackout restrictions unverified'})
            seen.add(service)
    return leads

def fetch(job):
    sport, league, path, day = job
    params = urllib.parse.urlencode({'dates':day.strftime('%Y%m%d'),'limit':300})
    url = f'https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?{params}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent':'SportsAlmanac/1.0','Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=22) as response:
            payload = json.load(response)
        if not isinstance(payload.get('events'),list):
            raise ValueError('Missing events array')
        result = []
        for event in payload['events']:
            try:
                instant = dt.datetime.fromisoformat(event['date'].replace('Z','+00:00')).astimezone(dt.timezone.utc)
                competition = event['competitions'][0]
                teams = competition['competitors']
                away = next(c for c in teams if c.get('homeAway')=='away')
                home = next(c for c in teams if c.get('homeAway')=='home')
                def team(c):
                    t = c.get('team') or {}
                    return t.get('displayName') or t.get('name') or 'TBC'
                result.append({
                    'id':f"espn:{path}:{event['id']}",
                    'sport':sport,'competition':league,
                    'title':f'{team(away)} at {team(home)}',
                    'start':instant.isoformat(timespec='seconds').replace('+00:00','Z'),
                    'liveStatus':event.get('status',{}).get('type',{}).get('description',''),
                    'fixtureSource':url,'broadcasts':[],
                    'broadcastLeads':espn_broadcast_leads(event,competition,url)
                })
            except (KeyError,TypeError,ValueError,StopIteration,IndexError):
                continue
        return result, None
    except Exception as exc:
        return [], f'{path} {day}: {exc}'

def valid_broadcast(b):
    return (isinstance(b,dict) and b.get('country') in ('UK','US')
        and isinstance(b.get('service'),str) and bool(b['service'].strip())
        and b.get('verified') is True
        and isinstance(b.get('sourceUrl'),str) and b['sourceUrl'].startswith('https://'))

def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    jobs = [(s,l,p,today+dt.timedelta(days=i)) for s,l,p in LEAGUES for i in range(32)]
    results = []
    errors = []
    with cf.ThreadPoolExecutor(max_workers=10) as pool:
        for games,err in pool.map(fetch,jobs):
            results.extend(games)
            if err: errors.append(err)
    if not results:
        raise RuntimeError('No fixtures retrieved; refusing to replace the feed')
    overrides = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    if not isinstance(overrides,dict):
        raise ValueError('broadcast-overrides.json must be an object keyed by fixture ID')
    unique = {}
    now = dt.datetime.now(dt.timezone.utc)
    end = now+dt.timedelta(days=30)
    for game in results:
        when = dt.datetime.fromisoformat(game['start'].replace('Z','+00:00'))
        if not now <= when < end: continue
        entry = overrides.get(game['id'], [])
        # Preserve backwards compatibility with list-based manual overrides.
        # A legacy object without country/verified cannot be considered confirmed.
        if isinstance(entry,dict): entry = entry.get('broadcasts', [])
        if not isinstance(entry,list): entry = []
        game['broadcasts'] = [b for b in entry if valid_broadcast(b)]
        unique[game['id']] = game
    if not unique:
        raise RuntimeError('No future fixtures found; refusing to replace the feed')
    output = {
        'updatedAt':now.isoformat(timespec='seconds').replace('+00:00','Z'),
        'schemaVersion':3,'source':'ESPN unofficial scoreboard; unverified US network leads; verified per-game manual overrides',
        'successfulChecks':len(jobs)-len(errors),'totalChecks':len(jobs),
        'errors':errors[:20],
        'items':sorted(unique.values(),key=lambda x:(x['start'],x['id']))
    }
    temp = OUT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    temp.replace(OUT)
    print(f"Saved {len(unique)} fixtures, {len(errors)} failed requests")

if __name__=='__main__': main()
