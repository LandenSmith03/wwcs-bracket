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
    """Scrape ESPN's scoreboard page and extract the embedded JSON data."""
    page_headers = {**HEADERS, 'Accept': 'text/html,application/xhtml+xml,*/*'}
    for url in [
        'https://www.espn.com/college-softball/scoreboard/',
        'https://www.espn.com/college-softball/scoreboard/_/seasontype/3',
    ]:
        try:
            r = requests.get(url, headers=page_headers, timeout=15)
            print(f'ESPN page {url.split("scoreboard")[1] or "/"}: HTTP {r.status_code}')
            if not r.ok:
                continue
            text = r.text
            # ESPN embeds all page data as window['__espnfitt__']={...}
            for marker in ["window['__espnfitt__']=", 'window["__espnfitt__"]=' ]:
                idx = text.find(marker)
                if idx == -1:
                    continue
                brace = text.find('{', idx + len(marker))
                if brace == -1:
                    continue
                try:
                    data, _ = json.JSONDecoder().raw_decode(text, brace)
                    evs = (data.get('page', {})
                               .get('content', {})
                               .get('scoreboard', {})
                               .get('events', []))
                    print(f'  → {len(evs)} events')
                    if evs:
                        return evs
                except Exception as e:
                    print(f'  ESPN JSON parse error: {e}')
        except Exception as e:
            print(f'ESPN page error: {e}')
    return []


def _search_ncaa_games(data, depth=0):
    """Recursively search Next.js page data for a list of game objects."""
    if depth > 8:
        return []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if any(k in data[0] for k in ('home', 'away', 'homeTeam', 'awayTeam', 'teams')):
            return data
        for item in data:
            result = _search_ncaa_games(item, depth + 1)
            if result:
                return result
    elif isinstance(data, dict):
        for k in ('games', 'contests', 'events', 'matches', 'items'):
            if k in data:
                result = _search_ncaa_games(data[k], depth + 1)
                if result:
                    return result
        for v in data.values():
            if isinstance(v, (dict, list)):
                result = _search_ncaa_games(v, depth + 1)
                if result:
                    return result
    return []


def fetch_ncaa():
    """Scrape NCAA.com WCWS pages and extract embedded Next.js JSON data."""
    page_headers = {**HEADERS, 'Accept': 'text/html,application/xhtml+xml,*/*',
                    'Referer': 'https://www.ncaa.com/'}
    for url in [
        'https://www.ncaa.com/championships/softball/d1',
        'https://www.ncaa.com/sports/softball/d1',
    ]:
        try:
            r = requests.get(url, headers=page_headers, timeout=15)
            print(f'NCAA page {url.split(".com")[1]}: HTTP {r.status_code}')
            if not r.ok:
                continue
            text = r.text
            # Next.js apps embed full page data in a __NEXT_DATA__ script tag
            idx = text.find('__NEXT_DATA__')
            if idx == -1:
                print('  No __NEXT_DATA__ found')
                continue
            start = text.find('>', idx) + 1
            end = text.find('</script>', start)
            if start <= 0 or end <= 0:
                continue
            try:
                data = json.loads(text[start:end])
                games = _search_ncaa_games(data)
                if games:
                    print(f'  → {len(games)} games')
                    return games
                print('  No game list found in NCAA data')
            except Exception as e:
                print(f'  NCAA JSON parse error: {e}')
        except Exception as e:
            print(f'NCAA page error: {e}')
    return []


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
