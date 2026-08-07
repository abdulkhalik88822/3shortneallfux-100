
import re
from difflib import SequenceMatcher

def normalize(text):
    return re.sub(r'[^a-z0-9 ]', '', text.lower())

def score(query, title):
    q = normalize(query)
    t = normalize(title)

    if q == t:
        return 100

    ratio = SequenceMatcher(None, q, t).ratio()
    if q in t:
        return int(ratio * 80 + 20)

    return int(ratio * 70)

def sort_results(query, files):
    return sorted(files, key=lambda x: score(query, x.get("file_name","")), reverse=True)
