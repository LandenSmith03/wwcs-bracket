import os, sys, json, requests
from datetime import datetime, timedelta, timezone

SUPA_URL = 'https://poklxjqcgggjlzzlutkh.supabase.co'
SUPA_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBva2x4anFjZ2dnamx6emx1dGtoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODAwMTcwMTUsImV4cCI6MjA5NTU5MzAxNX0.Q1XHkfRhvaUsIxUngdRvkVkVixOax0m3sRN2ZKLTXJs'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; wcws-bracket-bot/1.0)',
    'Accept': 'application/json',
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

VERIFIED = {'g1': 'textech', 'g2': 'tennessee', 'g7': 'tennessee'}


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
    urls = [
        'https://site.api.espn.com/apis/site/v2/sports/softball/college-softball/scoreboard',
        'https://site.api.espn.com/apis/site/v2/sports/softball/college-softball/scoreboard?seasontype=3',
        'https://site.api.espn.com/apis/site/v2/sports/softball/womens-college-softball/scoreboard',
        'https://site.api.espn.com/apis/site/v2/sports/softball/college-softball/scoreboard?limit=100&groups=90',
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            print(f'ESPN {url.split("scoreboard")[1] or "(base)"}: HTTP {r.status_code}')
            if r.ok:
                data = r.json()
                evs = data.get('events', [])
                print(f'  → {len(evs)} events')
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
        url = f'https://data.ncaa.com/casablanca/scoreboard/softball/d1/{y}/{m}/{day}/scoreboard.json'
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            print(f'NCAA {y}{m}{day}: HTTP {r.status_code}')
            if r.ok:
                data = r.json()
                raw = data.get('games', [])
                print(f'  → {len(raw)} games')
                games.extend(raw)
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
