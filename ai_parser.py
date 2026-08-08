import re

def parse_query(query):
    query = query.lower()

    year = re.search(r'(19|20)\d{2}', query)
    year = year.group() if year else None

    season = re.search(r'(s|season)\s?(\d+)', query)
    season = int(season.group(2)) if season else None

    episode = re.search(r'(e|episode)\s?(\d+)', query)
    episode = int(episode.group(2)) if episode else None

    clean = re.sub(r'(19|20)\d{2}', '', query)
    clean = re.sub(r'(s|season)\s?\d+', '', clean)
    clean = re.sub(r'(e|episode)\s?\d+', '', clean)

    return {
        "title": clean.strip(),
        "year": year,
        "season": season,
        "episode": episode
    }
