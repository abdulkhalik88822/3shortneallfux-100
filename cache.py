
cache = {}

def get_cache(query):
    return cache.get(query)

def set_cache(query, data):
    cache[query] = data
