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
    'g8': 'alabama',    # Alabama beat Nebraska 5-1 — May 30
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


def _espn_events_from_page(content, label):
    """Extract ESPN scoreboard events from a fully-rendered page."""
    for marker in ["window['__espnfitt__']=", 'window["__espnfitt__"]=']:
        idx = content.find(marker)
        if idx == -1:
            continue
        brace = content.find('{', idx + len(marker))
        if brace == -1:
            continue
        try:
            data, _ = json.JSONDecoder().raw_decode(content, brace)

            # --- DIAGNOSTIC: print top-level structure so we can find events ---
            print(f'  {label} top keys: {list(data.keys())}')
            page_d = data.get('page', {})
            print(f'  {label} page keys: {list(page_d.keys())}')
            content_d = page_d.get('content', {})
            print(f'  {label} content keys: {list(content_d.keys())}')
            for k, v in content_d.items():
                if isinstance(v, dict):
                    print(f'    content[{k!r}] keys: {list(v.keys())}')
                elif isinstance(v, list):
                    print(f'    content[{k!r}]: list of {len(v)}')
            # ------------------------------------------------------------------

            evs = (data.get('page', {})
                       .get('content', {})
                       .get('scoreboard', {})
                       .get('evts', []))
            print(f'  {label}: {len(evs)} events via page.content.scoreboard.evts')
            if evs:
                e0 = evs[0]
                print(f'  First event keys: {list(e0.keys())}')
                comp0 = (e0.get('competitions') or e0.get('cmptnrs') or [{}])[0]
                print(f'  First comp keys: {list(comp0.keys())}')
                cs = comp0.get('competitors') or comp0.get('cmpttrs') or []
                if cs:
                    print(f'  First competitor keys: {list(cs[0].keys())}')
            return evs
        except Exception as e:
            print(f'  {label} JSON parse error: {e}')
    print(f'  {label}: no __espnfitt__ in {len(content)}-char page')
    return []


def fetch_espn():
    """Use headless Chromium (bypasses Cloudflare) to scrape ESPN scoreboard."""
    today = datetime.now(timezone.utc)
    all_events = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                locale='en-US',
            )
            page = ctx.new_page()
            # Check today and yesterday — postseason games may appear on either date
            for delta in range(2):
                d = today - timedelta(days=delta)
                date_str = d.strftime('%Y%m%d')
                url = f'https://www.espn.com/college-softball/scoreboard/_/date/{date_str}'
                try:
                    page.goto(url, wait_until='networkidle', timeout=30000)
                    evs = _espn_events_from_page(page.content(), date_str)
                    all_events.extend(evs)
                except Exception as e:
                    print(f'  ESPN {date_str} error: {e}')
            browser.close()
    except ImportError:
        print('Playwright not installed')
    except Exception as e:
        print(f'ESPN Playwright error: {e}')
    return all_events


def fetch_ncaa():
    """Scrape stats.ncaa.org — the source softballR uses, no Cloudflare protection."""
    import re
    today = datetime.now(timezone.utc)
    all_games = []
    headers = {**HEADERS, 'Accept': 'text/html,application/xhtml+xml,*/*',
               'Referer': 'https://stats.ncaa.org/'}

    for delta in range(5):
        d = today - timedelta(days=delta)
        date_str = d.strftime('%m%%2F%d%%2F%Y')  # URL-encoded MM/DD/YYYY
        url = f'https://stats.ncaa.org/contests/scoreboards?division=1&sport_code=WSB&game_date={date_str}'
        try:
            r = requests.get(url, headers=headers, timeout=15)
            print(f'NCAA stats {d.strftime("%Y%m%d")}: HTTP {r.status_code} ({len(r.text)} chars)')
            if r.status_code == 403:
                print('  Blocked — stopping NCAA stats')
                break
            if not r.ok:
                continue
            games = _parse_ncaa_stats_html(r.text)
            if games:
                print(f'  → {len(games)} games parsed')
                all_games.extend(games)
            else:
                # Log snippet so we can see the structure and refine the parser
                clean = re.sub(r'<[^>]+>', ' ', r.text)
                clean = re.sub(r'\s+', ' ', clean).strip()
                print(f'  Text snippet: {clean[:400]!r}')
        except Exception as e:
            print(f'NCAA stats error: {e}')
    return all_games


def _parse_ncaa_stats_html(html):
    """
    Parse stats.ncaa.org scoreboard HTML.
    Looks for our 8 known team names and associated scores/status.
    """
    import re

    # Strip scripts, styles, and tags to get readable text blocks
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'[ \t]+', ' ', text)

    # Known team name variants as they appear on stats.ncaa.org
    TEAM_NAMES = {
        'Texas Tech': 'textech', 'Mississippi State': 'msstate',
        'Mississippi St.': 'msstate', 'Tennessee': 'tennessee',
        'Texas': 'texas', 'Alabama': 'alabama', 'UCLA': 'ucla',
        'Nebraska': 'nebraska', 'Arkansas': 'arkansas',
    }

    games = []
    # Find lines containing "Final" — each final game block has two teams + scores
    # Pattern: "TeamA N TeamB M Final" or similar
    final_blocks = re.finditer(
        r'((?:' + '|'.join(re.escape(t) for t in TEAM_NAMES) + r'))'
        r'\s+(\d+)\s+'
        r'((?:' + '|'.join(re.escape(t) for t in TEAM_NAMES) + r'))'
        r'\s+(\d+)\s+'
        r'(Final|F\b)',
        text, re.IGNORECASE
    )
    for m in final_blocks:
        t1_raw, s1, t2_raw, s2, _ = m.groups()
        t1 = next((v for k, v in TEAM_NAMES.items() if k.lower() == t1_raw.lower()), None)
        t2 = next((v for k, v in TEAM_NAMES.items() if k.lower() == t2_raw.lower()), None)
        if t1 and t2 and t1 != t2:
            games.append({
                'home': {'names': {'full': t1_raw}, 'score': str(s1)},
                'away': {'names': {'full': t2_raw}, 'score': str(s2)},
                'gameState': 'final',
            })
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
