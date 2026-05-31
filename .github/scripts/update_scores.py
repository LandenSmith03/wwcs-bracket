import os, sys, json, requests
from datetime import datetime, timedelta, timezone

SUPA_URL = 'https://poklxjqcgggjlzzlutkh.supabase.co'
SUPA_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBva2x4anFjZ2dnamx6emx1dGtoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODAwMTcwMTUsImV4cCI6MjA5NTU5MzAxNX0.Q1XHkfRhvaUsIxUngdRvkVkVixOax0m3sRN2ZKLTXJs'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.espn.com/',
}

# Maps fragments of a team display name to internal ID
TEAM_MAP = {
    'texas tech': 'textech',
    'red raiders': 'textech',
    'mississippi state': 'msstate',
    'mississippi st': 'msstate',
    'tennessee': 'tennessee',
    'volunteers': 'tennessee',
    'texas longhorns': 'texas',
    'texas ': 'texas',  # trailing space avoids matching "Texas Tech"
    ' texas': 'texas',
    'alabama': 'alabama',
    'crimson tide': 'alabama',
    'ucla': 'ucla',
    'bruins': 'ucla',
    'nebraska': 'nebraska',
    'cornhuskers': 'nebraska',
    'arkansas': 'arkansas',
    'razorbacks': 'arkansas',
}

GD = {
    'g1':  {'teams': ['textech', 'msstate']},
    'g2':  {'teams': ['texas', 'tennessee']},
    'g3':  {'teams': ['alabama', 'ucla']},
    'g4':  {'teams': ['nebraska', 'arkansas']},
    'g5':  {'from': ['l:g1', 'l:g2']},
    'g6':  {'from': ['l:g3', 'l:g4']},
    'g7':  {'from': ['w:g1', 'w:g2']},
    'g8':  {'from': ['w:g3', 'w:g4']},
    'g9':  {'from': ['w:g5', 'l:g7']},
    'g10': {'from': ['w:g6', 'l:g8']},
    'g11': {'from': ['w:g7', 'w:g9']},
    'g12': {'from': ['w:g7', 'w:g9'], 'ifnec': True},
    'g13': {'from': ['w:g8', 'w:g10']},
    'g14': {'from': ['w:g8', 'w:g10'], 'ifnec': True},
    'cf1': {'from': ['w:g11', 'w:g13']},
    'cf2': {'from': ['w:g11', 'w:g13']},
    'cf3': {'from': ['w:g11', 'w:g13'], 'ifnec': True},
}

VERIFIED = {
    'g1': 'textech',    # Texas Tech beat Mississippi State — May 28
    'g2': 'tennessee',  # Tennessee beat Texas — May 28
    'g3': 'alabama',    # Alabama beat UCLA — May 28
    'g4': 'nebraska',   # Nebraska beat Arkansas — May 28
    'g5': 'texas',      # Texas beat Mississippi State — May 29
    'g6': 'ucla',       # UCLA beat Arkansas — May 29
    'g7': 'tennessee',  # Tennessee beat Texas Tech — May 30
}


def norm(name):
    if not name:
        return None
    s = ' ' + name.lower().strip() + ' '
    for k, v in TEAM_MAP.items():
        if k in s:
            return v
    return None


def resolve(gid, winners):
    """Return [teamA, teamB] for a game, or [] if not yet determinable."""
    g = GD.get(gid)
    if not g:
        return []
    if 'teams' in g:
        return g['teams'][:]
    teams = []
    for src in g.get('from', []):
        pfx, sid = src.split(':')
        w = winners.get(sid)
        if pfx == 'w':
            if not w:
                return []
            teams.append(w)
        else:  # loser
            st = resolve(sid, winners)
            if len(st) != 2 or not w:
                return []
            loser = st[1] if st[0] == w else st[0]
            teams.append(loser)
    return teams if len(teams) == 2 else []


def find_gid(a, b, winners):
    pair = {a, b}
    for gid in GD:
        if set(resolve(gid, winners)) == pair:
            return gid
    return None


def supa_get_results():
    r = requests.get(
        f'{SUPA_URL}/rest/v1/results?select=game_id,winner',
        headers={**HEADERS, 'apikey': SUPA_KEY, 'Authorization': f'Bearer {SUPA_KEY}'},
        timeout=10
    )
    if r.ok:
        return {row['game_id']: row['winner'] for row in r.json() if row.get('winner')}
    print(f'Supabase read error: {r.status_code} {r.text[:200]}')
    return {}


def supa_upsert(gid, winner):
    r = requests.post(
        f'{SUPA_URL}/rest/v1/results',
        headers={
            **HEADERS,
            'apikey': SUPA_KEY,
            'Authorization': f'Bearer {SUPA_KEY}',
            'Content-Type': 'application/json',
            'Prefer': 'return=minimal,resolution=merge-duplicates',
        },
        json={'game_id': gid, 'winner': winner},
        timeout=10
    )
    return r.ok


def fetch_espn():
    today = datetime.now(timezone.utc)
    date_str = today.strftime('%Y%m%d')
    yesterday = (today - timedelta(days=1)).strftime('%Y%m%d')
    urls = [
        # CDN endpoint — used by ESPN's own website frontend
        f'https://cdn.espn.com/core/college-softball/scoreboard?xhr=1&limit=100&dates={date_str}',
        f'https://cdn.espn.com/core/college-softball/scoreboard?xhr=1&limit=100&dates={yesterday}',
        # site API with seasontype=3 (postseason)
        'https://site.api.espn.com/apis/site/v2/sports/softball/college-softball/scoreboard?seasontype=3&limit=100',
        # web API variant
        f'https://site.web.api.espn.com/apis/v2/sports/softball/college-softball/scoreboard?dates={date_str}&seasontype=3',
        f'https://site.web.api.espn.com/apis/v2/sports/softball/college-softball/scoreboard?dates={yesterday}&seasontype=3',
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            label = url.split('espn.com')[1][:60]
            print(f'ESPN {label}: HTTP {r.status_code}')
            if r.ok:
                data = r.json()
                # CDN wraps events under content.sbData
                evs = (data.get('content', {}).get('sbData', {}).get('events')
                       or data.get('events', []))
                print(f'  → {len(evs)} events')
                if evs:
                    return evs
        except Exception as e:
            print(f'ESPN error: {e}')
    return []


def fetch_ncaa():
    today = datetime.now(timezone.utc)
    start = datetime(2026, 5, 28, tzinfo=timezone.utc)
    games = []
    d = start
    while d <= today:
        y, m, day = d.year, f'{d.month:02d}', f'{d.day:02d}'
        # Try multiple NCAA API paths — casablanca 404s for postseason dates
        ncaa_urls = [
            f'https://data.ncaa.com/casablanca/scoreboard/softball/d1/{y}/{m}/{day}/scoreboard.json',
            f'https://ncaa-api.henrygd.me/scoreboard/softball/d1/{y}/{m}/{day}/scoreboard',
        ]
        for url in ncaa_urls:
            try:
                r = requests.get(url, headers=HEADERS, timeout=10)
                src = 'henrygd' if 'henrygd' in url else 'NCAA'
                print(f'{src} {y}{m}{day}: HTTP {r.status_code}')
                if r.ok:
                    data = r.json()
                    raw = data.get('games', [])
                    print(f'  → {len(raw)} games')
                    if raw:
                        games.extend(raw)
                        break
            except Exception as e:
                print(f'NCAA {y}{m}{day} error: {e}')
        d += timedelta(days=1)
    return games


def process_espn_events(events, winners):
    updated = 0
    for ev in events:
        comp = (ev.get('competitions') or [{}])[0]
        cs = comp.get('competitors', [])
        if len(cs) < 2:
            continue
        completed = comp.get('status', {}).get('type', {}).get('completed', False)
        if not completed:
            continue
        n0 = cs[0].get('team', {}).get('displayName', '')
        n1 = cs[1].get('team', {}).get('displayName', '')
        id0, id1 = norm(n0), norm(n1)
        if not id0 or not id1:
            print(f'  Unknown teams: "{n0}" / "{n1}"')
            continue
        gid = find_gid(id0, id1, winners)
        if not gid:
            print(f'  No game ID for {id0} vs {id1}')
            continue
        s0 = int(cs[0].get('score') or 0)
        s1 = int(cs[1].get('score') or 0)
        winner = id0 if s0 > s1 else id1
        if winners.get(gid) == winner:
            print(f'  {gid}: {winner} already recorded')
            continue
        if supa_upsert(gid, winner):
            print(f'  {gid}: {winner} → Supabase ✓')
            winners[gid] = winner
            updated += 1
        else:
            print(f'  {gid}: Supabase write failed')
    return updated


def process_ncaa_games(raw_games, winners):
    updated = 0
    for g in raw_games:
        gd = g.get('game') or g
        h_name = (gd.get('home') or {}).get('names', {}).get('full') or (gd.get('home') or {}).get('name', '')
        a_name = (gd.get('away') or {}).get('names', {}).get('full') or (gd.get('away') or {}).get('name', '')
        hid, aid = norm(h_name), norm(a_name)
        if not hid or not aid:
            continue
        st = (gd.get('gameState') or gd.get('status') or '').lower()
        if not ('final' in st or st == 'f' or st == 'post' or st == 'complete'):
            continue
        gid = find_gid(hid, aid, winners)
        if not gid:
            continue
        hs = int((gd.get('home') or {}).get('score') or 0)
        as_ = int((gd.get('away') or {}).get('score') or 0)
        winner = hid if hs > as_ else aid
        if winners.get(gid) == winner:
            continue
        if supa_upsert(gid, winner):
            print(f'  NCAA {gid}: {winner} → Supabase ✓')
            winners[gid] = winner
            updated += 1
    return updated


def main():
    print(f'=== WCWS Score Update {datetime.now(timezone.utc).isoformat()} ===')

    # Stop running after tournament ends
    if datetime.now(timezone.utc) > datetime(2026, 6, 7, tzinfo=timezone.utc):
        print('Tournament over — skipping')
        return

    winners = supa_get_results()
    for k, v in VERIFIED.items():
        winners.setdefault(k, v)
    print(f'Current results: {winners}')

    total = 0

    events = fetch_espn()
    if events:
        total += process_espn_events(events, winners)

    if total == 0:
        ncaa_games = fetch_ncaa()
        if ncaa_games:
            total += process_ncaa_games(ncaa_games, winners)

    print(f'Done — {total} result(s) updated')


if __name__ == '__main__':
    main()
