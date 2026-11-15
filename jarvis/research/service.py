"""Concrete research operations. No credentials, paid APIs or generated code."""

from jarvis.browser.controller import BrowserController
from jarvis.research.web import PublicSearch, PublicFetcher
from jarvis.research.google_docs import GoogleDocuments
from jarvis.research.report import export_pdf
import json


class ResearchServices:
    def __init__(self, root):
        self.root = root
        self.searcher = PublicSearch(root)
        self.fetcher = PublicFetcher()
        self.chatgpt = BrowserController(root)
        self.documents = GoogleDocuments(root)

    def search(self, query, context):
        results = self.searcher.search(query,context)
        return {"results":results,"engine":self.searcher.engine}

    def fetch(self, url, context):
        return self.fetcher.fetch(url,context)

    def pdf(self, report, sources, folder, context):
        return export_pdf(report,sources,folder,context)

    def review_with_chatgpt(self, report, sources, context):
        payload = {"titolo":report["title"],"sintesi":report["summary"][:600],
                   "fonti":[{"id":source["id"],"url":source["url"][:180]} for source in sources[:3]]}
        prompt = ("Esamina questa sintesi di ricerca e le fonti indicate. Segnala lacune, possibili errori e verifiche da fare. "
                  "Non inventare dati o riferimenti. Rispondi in italiano in modo conciso.\n"+json.dumps(payload,ensure_ascii=False))
        if len(prompt)>1800:
            payload["sintesi"] = payload["sintesi"][:250]
            prompt = "Verifica sintesi e fonti; segnala errori e limiti senza inventare dati:\n"+json.dumps(payload,ensure_ascii=False)
        sent = self.chatgpt.send(prompt,context)
        reply = self.chatgpt.wait_reply(sent["assistant_baseline"],context)
        return {"review":reply["reply"],"chatgpt_verified":True,"submitted":sent["submitted"]}
