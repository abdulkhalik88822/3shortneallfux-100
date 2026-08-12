import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database.smart_search import parse_search_query, build_strict_filter, relevance_score


def _matches(filename, mongo_filter):
    for condition in mongo_filter.get('$and', []):
        spec = condition['file_name']
        if not re.search(spec['$regex'], filename, re.I):
            return False
    return True

samples = [
    'Bad Moms (Movie 2016) mp4',
    'Bad Moms 2016 720p MkvCage mkv',
    'The Matchbreaker (2016) MP4',
    'Azhar (2016) MP4',
    'Mine 2016 mp4',
    'MOM 2017 Hindi DVDScr 700MB MP3 mkv',
    'Mom and Dad (2017) 720p BluRay mkv',
    'RRR 2022 S01E03 Hindi 1080p.mkv',
    'RRR S01 Episode 01.mkv',
    'RRR 2022 Movie.mkv',
]

spec = parse_search_query('Moms 2016')
f = build_strict_filter(spec)
matched = [x for x in samples if _matches(x, f)]
assert matched == ['Bad Moms (Movie 2016) mp4', 'Bad Moms 2016 720p MkvCage mkv'], matched

spec = parse_search_query('Mom 2017')
f = build_strict_filter(spec)
matched = [x for x in samples if _matches(x, f)]
assert 'MOM 2017 Hindi DVDScr 700MB MP3 mkv' in matched
assert not any('Bad Moms' in x for x in matched)

spec = parse_search_query('rrr 2022 s01 e03')
f = build_strict_filter(spec)
matched = [x for x in samples if _matches(x, f)]
assert matched == ['RRR 2022 S01E03 Hindi 1080p.mkv'], matched

spec = parse_search_query('episode 1')
f = build_strict_filter(spec)
matched = [x for x in samples if _matches(x, f)]
assert 'RRR S01 Episode 01.mkv' in matched

print('smart-search tests: OK')
