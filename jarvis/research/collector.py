"""Observe source quality and replan public searches within one authorized objective."""

from concurrent.futures import ThreadPoolExecutor,as_completed
from jarvis.core.models import UserError
from jarvis.research.quality import canonical_url,unique_sources


def collect_sources(plan,state,provider,execute,context,progress):
    candidates=[]
    attempted_urls=set()
    attempted_queries=set()
    queries=plan["queries"]
    state.update(source_failures=[],search_failures=[],coverage_rounds=[])
    for round_index in range(3):
        context.checkpoint()
        groups=[]
        for query in queries:
            context.checkpoint()
            key=" ".join(query.casefold().split())
            if key in attempted_queries:
                continue
            attempted_queries.add(key)
            progress("Cerco fonti: "+query)
            try:
                found=execute("search",{"query":query})
            except UserError as exc:
                state["search_failures"].append({"query":query,"error":str(exc)})
                progress("Ricerca senza risultati utilizzabili; provo le altre query.")
                continue
            state["searches"].append({"query":query,**found,"round":round_index+1})
            groups.append([item["url"] for item in found["results"]])
            progress("Ricerca fonti: "+found.get("engine","motore pubblico"))
        urls=list(dict.fromkeys(group[i] for i in range(max(map(len,groups),default=0)) for group in groups if i<len(group)))
        urls=[url for url in urls if canonical_url(url) not in attempted_urls][:8]
        attempted_urls.update(canonical_url(url) for url in urls)
        if urls:
            progress("Leggo e confronto le fonti pubbliche.")
            with ThreadPoolExecutor(max_workers=3,thread_name_prefix="research-source") as pool:
                futures={pool.submit(execute,"fetch",{"url":url},25):url for url in urls}
                for future in as_completed(futures):
                    context.checkpoint()
                    try:
                        candidates.append(future.result())
                    except UserError as exc:
                        state["source_failures"].append({"url":futures[future],"error":str(exc)})
                    progress(f"Pagine lette: {len(candidates)}.")
        candidates=unique_sources(candidates)
        progress("Controllo pertinenza, duplicati e copertura delle fonti.")
        selected=provider.relevant_sources(plan["topic"],candidates,context) if candidates else []
        state["sources"]=unique_sources(selected)
        coverage=provider.assess_research(plan["topic"],state["sources"],context)
        if len(state["sources"])<2:
            coverage={**coverage,"sufficient":False,"gaps":["Meno di due fonti distinte pertinenti.",*coverage["gaps"]][:4]}
        state["coverage_rounds"].append({"round":round_index+1,**coverage})
        if coverage["sufficient"]:
            break
        queries=[query for query in coverage["queries"] if " ".join(query.casefold().split()) not in attempted_queries]
        if not queries or round_index==2:
            break
        progress("Riformulo la ricerca per colmare le lacune rilevate.")
    if len(state["sources"])<2:
        raise UserError("Non ho trovato almeno due fonti distinte pertinenti, anche dopo la riformulazione. La ricerca resta incompleta.")
    state["coverage"]=state["coverage_rounds"][-1]
    return state["sources"]
