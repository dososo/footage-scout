"""Polite, allowlisted HTTPS. Every hop is checked before any bytes are requested."""
import email.utils, hashlib, ipaddress, json, os, pathlib, re, socket, threading, time
from contextlib import contextmanager
from urllib.parse import urljoin, urlsplit
import httpx
from . import __version__, robots
from .core import FscError, atomic_write

JSON_CAP = 20 << 20
READ_LIMIT = 120


def user_agent(env=os.environ):
    c = env.get("FSC_CONTACT_URL", "")
    ok = re.fullmatch(r"https://[A-Za-z0-9./_~-]+", c)
    return f"footage-scout/{__version__}" + (f" (+{c})" if ok else "")


def check_url(url, src, first):
    try:
        u = urlsplit(url)
        host, port = u.hostname, u.port
    except ValueError as e:
        raise FscError("malformed URL") from e
    if u.scheme != "https" or not host or u.username is not None or u.password is not None or port not in (None, 443):
        raise FscError(f"URL refused (https, no credentials, default port only): {host}")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise FscError("IP-literal host refused")
    if host in src["hosts"]:
        return host
    if not first and any(host.endswith(s) and len(host) > len(s) for s in src["redirect_host_suffixes"]):
        return host
    raise FscError(f"host not allowlisted: {host}")


class Http:
    def __init__(self, cache=None, transport=None, sleep=time.sleep, clock=time.time, resolver=None, log=None,
                 proxied=None, budget=60):
        self.cache = pathlib.Path(cache) if cache else None
        self.client = httpx.Client(transport=transport, follow_redirects=False, timeout=45, trust_env=transport is None,
                                   headers={"User-Agent": user_agent(), "Accept-Encoding": "identity"})
        self.sleep, self.clock, self.resolver, self.log = sleep, clock, resolver or self._dns, log
        self.proxied = proxied if proxied is not None else (lambda h: transport is None and _via_proxy(h))
        self.budget, self.used, self.last, self.blocked, self.robots = budget, {}, {}, {}, {}
        self.lock = threading.Lock()

    @staticmethod
    def _dns(host):
        return {x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}

    def _check_ip(self, host):
        # With a configured proxy, the proxy resolves names (local DNS may be synthetic), so only the allowlist applies.
        if self.proxied(host):
            return
        try:
            ips = self.resolver(host)
        except OSError as e:
            raise FscError(f"DNS failed: {host}") from e
        if not ips or any(not ipaddress.ip_address(i.split("%")[0]).is_global for i in ips):
            raise FscError(f"host resolves to a non-public address: {host}")

    def _stamp(self, host):
        return self.cache / "rate" / hashlib.sha256(host.encode()).hexdigest()[:16] if self.cache else None

    def _pace(self, host, src):
        if self.used.get(src["id"], 0) >= self.budget:
            raise FscError(f"request budget exhausted for {src['id']}")
        gap = max(src["politeness"]["min_interval_ms"] / 1000, self.robots.get(host, (0, {}))[1].get("delay", 0))
        last, st = self.last.get(host, 0), self._stamp(host)
        if st and st.is_file():
            try:
                last = max(last, float(st.read_text()))
            except ValueError:
                pass
        now = self.clock()
        wait = max(min(last, now) + gap - now, self.blocked.get(host, 0) - now)
        if wait > 120:
            raise FscError(f"{host} asked us to wait {int(wait)} s")
        if wait > 0:
            self.sleep(wait)
        self.used[src["id"]] = self.used.get(src["id"], 0) + 1
        self.last[host] = self.clock()
        if st:
            atomic_write(st, str(self.last[host]).encode())

    def _robots(self, host, src):
        """4xx means no rules; 5xx, 429, network failure or a refused redirect means everything is disallowed (RFC 9309)."""
        got = self.robots.get(host)
        if got and 0 <= self.clock() - got[0] < 86400:
            return got[1]
        f = self.cache / "robots" / hashlib.sha256(host.encode()).hexdigest()[:32] if self.cache else None
        if f and f.is_file() and 0 <= self.clock() - f.stat().st_mtime < 86400:
            txt, ts = f.read_text("utf-8", "replace"), f.stat().st_mtime
        else:
            url, txt, ts = f"https://{host}/robots.txt", "", self.clock()
            for hop in range(6):
                h = check_url(url, src, hop == 0)
                self._check_ip(h)
                self._pace(h, src)
                try:
                    with self.client.stream("GET", url) as r:
                        self._log("GET", h, r.status_code, src)
                        loc = r.headers.get("location")
                        if r.status_code in (301, 302, 303, 307, 308) and loc:
                            url = urljoin(url, loc)
                            continue
                        if r.status_code == 200:
                            buf = bytearray()
                            for b in r.iter_bytes():
                                buf += b
                                if len(buf) >= robots.CAP:
                                    break
                            del buf[robots.CAP:]
                            # a rule cut in half by the cap could be broader or narrower than intended: drop it
                            txt = bytes(buf).decode("utf-8", "replace")
                            txt = txt if len(buf) < robots.CAP else txt[:txt.rfind("\n") + 1]
                        elif not 400 <= r.status_code < 500 or r.status_code == 429:
                            raise FscError(f"{host}: robots.txt unavailable (HTTP {r.status_code})")
                        break
                except httpx.HTTPError as e:
                    raise FscError(f"{host}: robots.txt unavailable ({type(e).__name__})") from e
            else:
                raise FscError(f"{host}: robots.txt redirects too often")
            if f:
                atomic_write(f, txt.encode())
        self.robots[host] = (ts, robots.parse(txt))
        return self.robots[host][1]

    @contextmanager
    def request(self, method, url, src):
        """Serial (one in flight), manual redirects, retry on 429/503 and connection errors."""
        if src["id"] == "commons" and "(+" not in self.client.headers["user-agent"]:
            raise FscError("Wikimedia requires a contact in the User-Agent: set FSC_CONTACT_URL=https://...")
        with self.lock:
            hop = tries = 0
            while True:
                host = check_url(url, src, hop == 0)
                self._check_ip(host)
                # documented APIs (T1) follow their API policy; every page-read source follows robots.txt, on every hop
                if src["tier"] != "T1" and not robots.allowed(self._robots(host, src), url):
                    raise FscError(f"robots.txt disallows this path on {host}")
                self._pace(host, src)
                try:
                    r = self.client.send(self.client.build_request(method, url), stream=True)
                except httpx.HTTPError as e:
                    self._log(method, host, type(e).__name__, src)
                    tries += 1
                    if tries > 2:
                        raise FscError(f"{host}: {type(e).__name__}") from e
                    self.sleep(2 ** tries)
                    continue
                self._log(method, host, r.status_code, src)
                if r.status_code in (429, 503):
                    ra = _retry_after(r.headers.get("retry-after"), self.clock())
                    r.close()
                    tries += 1
                    self.blocked[host] = self.clock() + max(2 ** tries, ra)
                    if tries > 3:
                        raise FscError(f"{host}: HTTP {r.status_code}")
                    continue
                if r.status_code in (301, 302, 303, 307, 308):
                    loc = r.headers.get("location")
                    r.close()
                    hop += 1
                    if not loc or hop > 5:
                        raise FscError("bad redirect")
                    url = urljoin(url, loc)
                    continue
                try:
                    if r.status_code != 200:
                        raise FscError(f"{host}: HTTP {r.status_code}")
                    yield r, host
                finally:
                    r.close()
                return

    def _log(self, method, host, status, src):
        if self.log:
            self.log(dict(ts=round(self.last[host], 3), source=src["id"], host=host, method=method, status=status))

    def get(self, url, src, ttl=86400, cap=None):
        f = self.cache / "http" / hashlib.sha256(url.encode()).hexdigest() if self.cache else None
        check_url(url, src, True)
        if f and f.is_file() and 0 <= self.clock() - f.stat().st_mtime < ttl:
            return f.read_bytes()
        buf = bytearray()
        try:
            with self.request("GET", url, src) as (r, host):
                end = self.clock() + READ_LIMIT     # a per-read timeout alone lets a slow drip go on for ever
                for b in r.iter_bytes():
                    buf += b
                    if self.clock() > end:
                        raise FscError(f"{host}: page took longer than {READ_LIMIT} s")
                    if len(buf) > (cap or JSON_CAP):
                        raise FscError("response too large")
        except httpx.HTTPError as e:
            raise FscError(f"read failed: {type(e).__name__}") from e
        if f:
            atomic_write(f, bytes(buf))
        return bytes(buf)

    def json(self, url, src):
        try:
            return json.loads(self.get(url, src))
        except ValueError as e:
            raise FscError(f"{src['id']}: response is not JSON") from e


def _retry_after(v, now):
    if not v:
        return 0
    try:
        return max(0, float(v))
    except ValueError:
        try:
            return max(0, email.utils.parsedate_to_datetime(v).timestamp() - now)
        except (ValueError, TypeError):
            return 0


def _via_proxy(host):
    from urllib.request import getproxies_environment, proxy_bypass_environment
    p = getproxies_environment()
    return bool(p.get("https") or p.get("all")) and not proxy_bypass_environment(host)
