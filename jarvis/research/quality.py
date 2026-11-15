"""Bounded public research assessment. Model opinions never grant permissions."""

import hashlib
import re
import unicodedata
from urllib.parse import urlsplit,urlunsplit
from jarvis.core.models import UserError


def _texts(value, maximum, length):
    return isinstance(value,list) and len(value)<=maximum and all(isinstance(s,str) and 0<len(s.strip())<=length for s in value)


def validate_coverage(value):
    if (not isinstance(value,dict) or set(value)!={"sufficient","gaps","queries"}
            or type(value["sufficient"]) is not bool or not _texts(value["gaps"],4,1000)
            or not _texts(value["queries"],2,300) or (value["sufficient"] and value["queries"])
            or any(len(query.strip())<3 for query in value["queries"])):
        raise UserError("Valutazione della copertura non valida.")
    return value


def validate_review(value):
    if (not isinstance(value,dict) or set(value)!={"approved","issues","notes"}
            or type(value["approved"]) is not bool or not _texts(value["issues"],6,2000)
            or not _texts(value["notes"],4,1000) or value["approved"]==bool(value["issues"])):
        raise UserError("Revisione del rapporto non valida.")
    return value


def grounded_review(value,report,sources):
    """Accept blocking findings only when both cited passages exist verbatim."""
    if not isinstance(value,dict) or set(value)!={"issues","notes"} or not isinstance(value["issues"],list) or len(value["issues"])>4 or not _texts(value["notes"],3,1000):
        raise UserError("Revisione strutturata non valida.")
    def normalize(text):
        return " ".join(unicodedata.normalize("NFKC",text).casefold().replace("’","'").split())
    passages=[report["summary"],*[p for section in report["sections"] for p in section["paragraphs"]]]
    known={source["id"]:source for source in sources}
    issues=[]
    for item in value["issues"]:
        if (not isinstance(item,dict) or set(item)!={"claim","source_id","evidence","reason"}
                or type(item["source_id"]) is not int or item["source_id"] not in known
                or any(not isinstance(item[k],str) or not 5<=len(item[k])<=2000 for k in ("claim","evidence","reason"))
                or not any(normalize(item["claim"]) in normalize(p) for p in passages)
                or normalize(item["evidence"]) not in normalize(known[item["source_id"]]["text"])):
            raise UserError("La revisione cita un passaggio non presente nel rapporto o nelle fonti.")
        if normalize(item["claim"]) in normalize(item["evidence"]) or normalize(item["evidence"]) in normalize(item["claim"]):
            continue  # An identical statement cannot be evidence of a contradiction.
        issues.append(f"Affermazione: {item['claim']} | Fonte [{item['source_id']}]: {item['evidence']} | Correzione: {item['reason']}")
    return validate_review({"approved":not issues,"issues":issues,"notes":value["notes"]})


def review_passages(report,sources):
    """Assign immutable IDs to actual passages; the model selects IDs, never invents quotes."""
    def fragments(text):
        for sentence in re.split(r"(?<=[.!?])\s+|\n+",text):
            for offset in range(0,len(sentence),700):
                chunk=sentence[offset:offset+700].strip()
                if len(chunk)>=5:
                    yield chunk
    claims={}
    for paragraph in [report["summary"],*[p for s in report["sections"] for p in s["paragraphs"]]]:
        for fragment in fragments(paragraph):
            claims[f"A{len(claims)+1}"]=fragment
    evidence={}
    for source in sources:
        for index,fragment in enumerate(fragments(source["text"][:5500]),1):
            evidence[f"F{source['id']}_{index}"]={"source_id":source["id"],"text":fragment}
    return claims,evidence


def canonical_url(url):
    parsed=urlsplit(url)
    return urlunsplit((parsed.scheme.casefold(),parsed.netloc.casefold(),parsed.path.rstrip("/"),parsed.query,""))


def unique_sources(sources):
    seen_urls,seen_texts=set(),set()
    result=[]
    for source in sources:
        key=canonical_url(source["url"])
        fingerprint=hashlib.sha256(" ".join(source["text"].casefold().split()).encode()).hexdigest()
        if key in seen_urls or fingerprint in seen_texts:
            continue
        seen_urls.add(key);seen_texts.add(fingerprint)
        result.append(dict(source))
    for index,source in enumerate(result,1):
        source["id"]=index
    return result
