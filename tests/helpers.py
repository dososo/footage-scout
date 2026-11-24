import httpx
from footage_scout.http import Http
class Clock:
    def __init__(s): s.t = 1e9; s.slept = []
    def __call__(s): return s.t
    def sleep(s, n): s.slept.append(n); s.t += n
def make(handler, cache=None, ips=("93.184.216.34",), **k):
    c = Clock(); calls = []
    def h(r): calls.append((r.method, str(r.url))); return handler(r)
    x = Http(cache=cache, transport=httpx.MockTransport(h), sleep=c.sleep, clock=c, resolver=lambda h: set(ips), log=k.pop("log", None), **k)
    return x, c, calls
