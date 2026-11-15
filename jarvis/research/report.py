"""Validated source citations and exportable PDF artifacts, using existing Qt."""

from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import secrets

from jarvis.core.models import UserError


def validate_report(report, sources):
    if not isinstance(report, dict) or set(report) != {"title", "summary", "sections", "limitations"}:
        raise UserError("Il modello non ha prodotto un rapporto strutturato valido.")
    if (not isinstance(report["title"], str) or not 1 <= len(report["title"]) <= 200
            or not isinstance(report["summary"], str) or not 1 <= len(report["summary"]) <= 2500
            or not isinstance(report["sections"], list) or not 1 <= len(report["sections"]) <= 12
            or not isinstance(report["limitations"], list) or any(not isinstance(text,str) for text in report["limitations"])):
        raise UserError("Dimensione o campi del rapporto non validi.")
    ids = {source["id"] for source in sources}
    for section in report["sections"]:
        if (not isinstance(section,dict) or set(section) != {"heading","paragraphs","source_ids"}
                or not isinstance(section["heading"],str) or not isinstance(section["paragraphs"],list)
                or not section["paragraphs"] or any(not isinstance(p,str) or len(p)>5000 for p in section["paragraphs"])
                or not isinstance(section["source_ids"],list) or not section["source_ids"]
                or any(type(identifier) is not int or identifier not in ids for identifier in section["source_ids"])):
            raise UserError("Il rapporto cita fonti inesistenti o contiene sezioni non verificabili.")
    return report


def report_text(report, sources):
    lines = [report["title"], "", report["summary"], ""]
    for section in report["sections"]:
        lines.extend([section["heading"], *section["paragraphs"], "Fonti: " + ", ".join(f"[{n}]" for n in section["source_ids"]), ""])
    if report["limitations"]:
        lines.extend(["Limiti della ricerca", *report["limitations"], ""])
    lines.append("Fonti consultate")
    lines.extend(f"[{source['id']}] {source['title']} — {source['url']} (consultata {source['retrieved_at_utc']})" for source in sources)
    return "\n".join(lines)


def report_html(report, sources):
    escape = html.escape
    parts = ["<!doctype html><html><head><meta charset='utf-8'><style>body{font-family:'Segoe UI';font-size:10pt;color:#18263a}h1{font-size:24pt;color:#102c54}h2{font-size:15pt;color:#15496e}p{line-height:1.4}a{color:#1552a0}li{margin-bottom:8px}</style></head><body>",
             "<h1>"+escape(report["title"])+"</h1>","<p>"+escape(report["summary"])+"</p>"]
    for section in report["sections"]:
        parts.append("<h2>"+escape(section["heading"])+"</h2>")
        parts.extend("<p>"+escape(p)+"</p>" for p in section["paragraphs"])
        parts.append("<p>Fonti: "+", ".join(f"<a href='#s{n}'>[{n}]</a>" for n in section["source_ids"])+"</p>")
    if report["limitations"]:
        parts.extend(["<h2>Limiti della ricerca</h2>",*['<p>'+escape(p)+'</p>' for p in report["limitations"]]])
    parts.append("<h2>Fonti consultate</h2><ol>")
    for source in sources:
        parts.append(f"<li value='{source['id']}' id='s{source['id']}'>{escape(source['title'])}<br><a href='{escape(source['url'],quote=True)}'>{escape(source['url'])}</a><br>Consultata: {escape(source['retrieved_at_utc'])}</li>")
    return "".join(parts)+"</ol></body></html>"


def create_job(root):
    base = root.resolve() / "data/reports"
    if base.is_symlink() or base.is_junction() or not base.resolve().is_relative_to(root.resolve() / "data"):
        raise UserError("Cartella rapporti non valida.")
    base.mkdir(parents=True,exist_ok=True)
    job = base / (datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3))
    job.mkdir()
    return job


def validate_pdf(path, *, expected_title=None):
    from PySide6.QtPdf import QPdfDocument
    path = Path(path)
    with path.open("rb") as stream:
        signature = stream.read(5)
    if path.stat().st_size < 500 or signature != b"%PDF-":
        raise UserError("Il file prodotto non e' un PDF valido.")
    document = QPdfDocument()
    error = document.load(str(path))
    if error != QPdfDocument.Error.None_ or document.pageCount() < 1:
        raise UserError("Impossibile verificare le pagine del PDF.")
    text = "\n".join(document.getAllText(page).text() for page in range(min(document.pageCount(), 40)))
    if expected_title and " ".join(expected_title.casefold().split()) not in " ".join(text.casefold().split()):
        raise UserError("Il PDF non contiene il titolo del rapporto previsto.")
    result = {"path":str(path.resolve()),"pages":document.pageCount(),"bytes":path.stat().st_size,
              "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"verified":True}
    document.close()
    return result


def export_pdf(report, sources, folder, context):
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPdfWriter, QPageSize, QTextDocument
    context.checkpoint()
    content = report_html(report, sources)
    (folder/"rapporto.html").write_text(content,encoding="utf-8")
    (folder/"rapporto.txt").write_text(report_text(report,sources),encoding="utf-8")
    (folder/"fonti.json").write_text(json.dumps(sources,ensure_ascii=False,indent=2),encoding="utf-8")
    path = folder/"ricerca.pdf"
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(16,16,16,16))
    writer.setTitle(report["title"])
    writer.setCreator("JARVIS")
    document = QTextDocument()
    document.setHtml(content)
    document.print_(writer)
    del document, writer
    context.checkpoint()
    return validate_pdf(path,expected_title=report["title"])
