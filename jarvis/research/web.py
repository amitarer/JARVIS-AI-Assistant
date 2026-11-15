"""Public source collection. Sources are data and never executable instructions."""

from datetime import datetime, timezone
from html.parser import HTMLParser
import ipaddress
import http.client
import json
import re
import socket
import ssl
from urllib.parse import urlsplit, urljoin, urlencode

from jarvis.browser.controller import BrowserController
from jarvis.core.models import UserError, UserActionRequired


def public_url(url, *, allow_loopback=False):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError
        if parsed.port not in {None, 80, 443} and not allow_loopback:
            raise ValueError
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses) and not allow_loopback:
            raise ValueError
        return url
    except (ValueError, OSError):
        raise UserError("La ricerca puo' leggere soltanto indirizzi web pubblici HTTP/HTTPS.") from None


class SourceText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.title = False
        self.titles = []
        self.parts = []
        self.main_depth = 0
        self.main_parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"main","article"}:
            self.main_depth += 1
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header"}:
            self.skip += 1
        if tag == "title":
            self.title = True
        if tag in {"p", "h1", "h2", "h3", "li", "br"}:
            self.parts.append("\n")
            if self.main_depth:
                self.main_parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"main","article"}:
            self.main_depth = max(0,self.main_depth-1)
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header"}:
            self.skip = max(0, self.skip - 1)
        if tag == "title":
            self.title = False

    def handle_data(self, data):
        if self.title:
            self.titles.append(data)
        if not self.skip:
            self.parts.append(data)
            if self.main_depth:
                self.main_parts.append(data)


def public_get(url, context, *, allow_loopback=False):
    """Pin a checked IP to the socket, including after every redirect (no DNS rebind)."""
    current = url
    for _ in range(5):
        context.checkpoint()
        public_url(current, allow_loopback=allow_loopback)
        parsed = urlsplit(current)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(parsed.hostname,port,type=socket.SOCK_STREAM)
        if not addresses or (not allow_loopback and any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses)):
            raise UserError("La fonte non usa un indirizzo pubblico.")
        connection = http.client.HTTPConnection(parsed.hostname,port,timeout=min(6,context.remaining))
        sock = None
        try:
            family, kind, protocol, _, address = addresses[0]
            sock = socket.socket(family,kind,protocol)
            sock.settimeout(min(6,context.remaining))
            sock.connect(address)
            if parsed.scheme == "https":
                sock = ssl.create_default_context().wrap_socket(sock,server_hostname=parsed.hostname)
            connection.sock = sock
            connection.request("GET",parsed.path + ("?"+parsed.query if parsed.query else "") or "/",
                               headers={"User-Agent":"JARVISResearch/1.0 (local desktop research)","Accept":"text/html,text/plain,application/json"})
            response = connection.getresponse()
            if response.status in {301,302,303,307,308} and response.getheader("Location"):
                current = urljoin(current,response.getheader("Location"))
                continue
            if response.status != 200:
                raise UserError(f"Fonte non disponibile (HTTP {response.status}).")
            raw = bytearray()
            while len(raw)<=1500000:
                context.checkpoint()
                chunk = response.read(32768)
                if not chunk:
                    break
                raw.extend(chunk)
            if len(raw)>1500000:
                raise UserError("Pagina oltre il limite di lettura.")
            return current,response.headers,bytes(raw)
        except (OSError,http.client.HTTPException):
            context.checkpoint()
            raise UserError("La fonte non risponde entro il tempo previsto.") from None
        finally:
            connection.close()
            if sock:
                sock.close()
    raise UserError("Troppi reindirizzamenti nella fonte.")


class PublicFetcher:
    def __init__(self, *, allow_loopback=False):
        self.allow_loopback = allow_loopback

    def fetch(self, url, context):
        current, headers, raw = public_get(url,context,allow_loopback=self.allow_loopback)
        if headers.get_content_type() not in {"text/html","text/plain","application/xhtml+xml"}:
            raise UserError("La fonte non e' una pagina testuale supportata.")
        try:
            decoded = raw.decode(headers.get_content_charset() or "utf-8",errors="replace")
        except LookupError:
            decoded = raw.decode("utf-8",errors="replace")
        parser = SourceText()
        parser.feed(decoded)
        main = " ".join(parser.main_parts)
        text = re.sub(r"[ \t]+", " ", main if len(main)>120 else " ".join(parser.parts))
        text = re.sub(r"\n\s*\n+", "\n", text).strip()[:18000]
        if len(text)<120:
            raise UserError("La fonte non contiene testo sufficiente per una ricerca verificabile.")
        return {"url":current,"title":" ".join(parser.titles).strip()[:250] or urlsplit(current).hostname,
                "text":text,"retrieved_at_utc":datetime.now(timezone.utc).isoformat()}


class PublicSearch:
    """Google search; public MediaWiki discovery when Google requires human verification."""
    def __init__(self,root):
        self.google = GoogleSearch(root)
        self.engine = "Google"
        self.google_unavailable = False

    def search(self,query,context):
        if not self.google_unavailable:
            try:
                self.engine = "Google"
                return self.google.search(query,context)
            except (UserActionRequired,UserError):
                context.checkpoint()
                self.google_unavailable = True
        self.engine = "MediaWiki: ricerca pubblica e riferimenti esterni (Google non disponibile)"
        language = "en"
        def api(parameters):
            _,_,raw = public_get(f"https://{language}.wikipedia.org/w/api.php?"+urlencode({"format":"json",**parameters}),context)
            try:
                return json.loads(raw)
            except ValueError:
                raise UserError("Risposta del servizio di ricerca non valida.") from None
        result = api({"action":"query","list":"search","srsearch":query,"srlimit":3})
        hits = result.get("query",{}).get("search",[])
        if not hits:
            language = "it"
            result = api({"action":"query","list":"search","srsearch":query,"srlimit":3})
            hits = result.get("query",{}).get("search",[])
        if not hits:
            raise UserError("Nessun risultato pubblico pertinente. Prova una query piu' specifica o completa la verifica Google.")
        pages = api({"action":"query","pageids":"|".join(str(hit["pageid"]) for hit in hits),"prop":"extlinks|info","inprop":"url","ellimit":100})
        terms = set(re.findall(r"[a-z]{4,}",query.casefold()))-{"site","fonti","ricerca","sources","evidence","scientific"}
        links = {}
        for page in pages.get("query",{}).get("pages",{}).values():
            for link in page.get("extlinks",[]):
                url = link.get("*","")
                host = urlsplit(url).hostname or ""
                if not url.startswith("https://") or any(part in host for part in ("youtube.","facebook.","twitter.","archive.org","webcitation.")):
                    continue
                score = sum(2 for term in terms if term in url.casefold())
                score += 5 if any(part in host for part in (".gov",".edu",".int","esa.int","nature.com","science.org")) else 0
                if score:
                    links[url] = {"url":url,"title":page.get("title",host)+" · riferimento esterno","score":score}
        ranked = sorted(links.values(),key=lambda item:item["score"],reverse=True)[:6]
        ranked.extend({"url":page["fullurl"],"title":page["title"]} for page in pages.get("query",{}).get("pages",{}).values() if page.get("fullurl"))
        return [{"url":item["url"],"title":item["title"]} for item in ranked]


SEARCH_JS = r'''(() => {
 const blocked = !!document.querySelector('#captcha-form,iframe[src*="recaptcha"]') || /unusual traffic|traffico insolito/i.test(document.body.innerText.slice(0,3000));
 const consent = location.hostname==='consent.google.com';
 const links=[...document.querySelectorAll('a')].filter(a=>a.querySelector('h3')).map(a=>({url:a.href,title:a.querySelector('h3').innerText}));
 return {blocked,consent,links:links.filter(x=>/^https?:/.test(x.url)).slice(0,10)};
})()'''


class GoogleSearch:
    def __init__(self, root):
        self.browser = BrowserController(root, allowed_origin="https://www.google.com")
        self.current_query = None

    def search(self, query, context):
        url = "https://www.google.com/search?" + urlencode({"q":query,"hl":"it","num":7})
        if self.browser.target_id and self.current_query != query:
            try:
                self.browser.navigate(url, context)
            except UserError:
                self.browser.open_chat(context, url=url)
        elif not self.browser.target_id:
            self.browser.open_chat(context, url=url)
        self.current_query = query
        for _ in range(15):
            context.checkpoint()
            try:
                state = self.browser._evaluate(SEARCH_JS, context)
            except UserError:
                raise UserActionRequired("Completa eventuali consensi o verifiche nella scheda Google dedicata.") from None
            if state.get("blocked"):
                raise UserActionRequired("Google richiede una verifica manuale nella finestra dedicata.")
            if state.get("links"):
                return state["links"]
            context.cancellation.wait(0.3)
        raise UserError("Google non ha fornito risultati leggibili. Completa eventuali consensi nella sua scheda.")
