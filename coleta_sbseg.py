#!/usr/bin/env python3
import argparse
import csv
import json
import re
import signal
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

SOL_OAI = "https://sol.sbc.org.br/index.php/{venue}/oai"
NS_OAI = "http://www.openarchives.org/OAI/2.0/"
NS_DC = "http://purl.org/dc/elements/1.1/"
DBLP = "https://dblp.org/search/publ/api"
IBGE = "https://servicodados.ibge.gov.br/api/v2/censos/nomes/{nome}?sexo={sexo}"
CABECALHO = {"User-Agent": "estudo-genero-wpos/1.0 (pesquisa academica)"}
CACHE = {}  
VERSAO = "2026-11-03-f"  
COR_MULHERES = "#D81B7A" 
FILTROS = {"min_paginas": 0} 

def obter_json(url, tentativas=4, pausa=2.0):
    ultimo_erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers=CABECALHO)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as erro: 
            ultimo_erro = erro
            time.sleep(pausa * (i + 1))
    print(f"[aviso] falha em {url}: {ultimo_erro}", file=sys.stderr)
    return None

TITULOS_IGNORADOS = re.compile(
    r"^(pref[aá]cio|apresenta[cç][aã]o|front matter|[íi]ndice|sum[aá]rio|"
    r"comit[eê]|organiza[cç][aã]o|editorial|palestra|keynote)", re.I)


def obter_xml(url, tentativas=4, pausa=2.0):
    ultimo_erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers=CABECALHO)
            with urllib.request.urlopen(req, timeout=120) as resp:
                return ET.fromstring(resp.read())
        except Exception as erro:
            ultimo_erro = erro
            time.sleep(pausa * (i + 1))
    print(f"[aviso] falha em {url}: {ultimo_erro}", file=sys.stderr)
    return None


def baixar_evento_sol(venue):
    arquivo = Path(CACHE["pasta"]) / f"oai_{venue}.json" if CACHE.get("pasta") else None
    if arquivo and arquivo.exists() and not CACHE.get("refazer"):
        print(f"       usando cache local {arquivo} (use --refazer para baixar de novo)")
        return json.loads(arquivo.read_text(encoding="utf-8"))
    base = SOL_OAI.format(venue=venue)
    url = f"{base}?verb=ListRecords&metadataPrefix=oai_dc"
    registros, tokens_vistos, sem_novos, pagina = [], set(), 0, 0
    interrompido = []
    handler_anterior = signal.signal(signal.SIGINT, lambda *_: interrompido.append(1))
    while url and not interrompido:
        raiz = obter_xml(url)
        if raiz is None:
            break
        erro_oai = raiz.find(f".//{{{NS_OAI}}}error")
        if erro_oai is not None:
            print(f"[aviso] o SOL respondeu com erro OAI '{erro_oai.get('code')}': "
                  f"{(erro_oai.text or '').strip()}", file=sys.stderr)
            break
        n_pagina = apagados = novos = 0
        for rec in raiz.iter(f"{{{NS_OAI}}}record"):
            n_pagina += 1
            cab = rec.find(f"{{{NS_OAI}}}header")
            if cab is not None and cab.get("status") == "deleted":
                apagados += 1
                continue
            meta = rec.find(f"{{{NS_OAI}}}metadata")
            if meta is None:
                continue
            campos = defaultdict(list)
            for el in meta.iter():
                if el.tag.startswith(f"{{{NS_DC}}}"):
                    campos[el.tag.split("}")[1]].append((el.text or "").strip())
            registros.append(campos)
            novos += 1
        pagina += 1
        print(f"       página {pagina}: {n_pagina} registros ({novos} válidos, {apagados} apagados); "
              f"total válido: {len(registros)}", flush=True)
        token = raiz.find(f".//{{{NS_OAI}}}resumptionToken")
        texto = (token.text or "").strip() if token is not None else ""
        sem_novos = sem_novos + 1 if novos == 0 else 0
        if (n_pagina == 0 or not texto or texto in tokens_vistos
                or sem_novos >= 3 or pagina >= 200):
            break
        tokens_vistos.add(texto)
        url = f"{base}?verb=ListRecords&resumptionToken={urllib.parse.quote(texto)}"
        time.sleep(1)
    signal.signal(signal.SIGINT, handler_anterior)
    if interrompido:
        print(f"[aviso] coleta interrompida: seguindo com os {len(registros)} registros já recebidos "
              "(cache não gravado).", file=sys.stderr)
    elif arquivo and registros:
        arquivo.write_text(json.dumps(registros, ensure_ascii=False), encoding="utf-8")
    return registros


def nome_de_dc(creator):
    c = creator.strip()
    if "," in c:
        sobrenome, _, resto = c.partition(",")
        return f"{resto.strip()} {sobrenome.strip()}".strip()
    return c


def paginas_do_registro(campos):
    for s in campos.get("source", []):
        m = re.search(r";\s*(\d+)-(\d+)\s*$", s)
        if s.startswith("Anais") and m:
            n = int(m.group(2)) - int(m.group(1)) + 1
            return n if n > 0 else None
    return None


def artigos_do_evento_sol(venue, ano_min, ano_max):
    vistos, artigos = set(), []
    descartes, brutos, exemplo = Counter(), 0, None
    for campos in baixar_evento_sol(venue):
        brutos += 1
        exemplo = exemplo or dict(campos)
        titulo = (campos.get("title") or [""])[0]
        autores = [nome_de_dc(c) for c in campos.get("creator", []) if c.strip()]
        ano = next((int(m.group(1)) for d in campos.get("date", [])
                    if (m := re.match(r"(\d{4})", d))), None)
        ident = next((i for i in campos.get("identifier", []) if i.startswith("http")), titulo)
        if not autores:
            descartes["sem autores"] += 1
            continue
        if ano is None:
            descartes["sem data"] += 1
            continue
        if not ano_min <= ano <= ano_max:
            descartes["fora do intervalo de anos"] += 1
            continue
        if TITULOS_IGNORADOS.match(titulo):
            descartes["prefácio/apresentação/etc."] += 1
            continue
        pag = paginas_do_registro(campos)
        if FILTROS["min_paginas"] and pag is not None and pag < FILTROS["min_paginas"]:
            descartes[f"menos de {FILTROS['min_paginas']} páginas"] += 1
            continue
        if ident in vistos:
            descartes["duplicado"] += 1
            continue
        vistos.add(ident)
        artigos.append({
            "venue": venue, "chave": ident, "ano": ano, "titulo": titulo,
            "autores": autores,
            "tipo": ";".join(campos.get("type", [])),
            "fonte": ";".join(campos.get("source", [])),
        })
    print(f"       {brutos} registros brutos recebidos; descartados: {dict(descartes) or 'nenhum'}")
    if brutos and not artigos:
        print("       exemplo de registro bruto (para diagnóstico):", exemplo)
    return artigos


def diagnosticar(venues):
    for v in venues:
        url = SOL_OAI.format(venue=v) + "?verb=Identify"
        print(f"GET {url}")
        raiz = obter_xml(url, tentativas=1)
        if raiz is None:
            print("  -> sem resposta utilizável (veja o aviso acima)")
            continue
        nome = raiz.find(f".//{{{NS_OAI}}}repositoryName")
        erro = raiz.find(f".//{{{NS_OAI}}}error")
        print("  -> resposta XML recebida | repositório:",
              nome.text if nome is not None else "(sem repositoryName)",
              "| erro OAI:", (erro.text or erro.get("code")) if erro is not None else "nenhum")
    url = IBGE.format(nome="MARIA", sexo="F")
    print(f"GET {url}")
    dados = obter_json(url, tentativas=1)
    print("  -> IBGE OK, frequência de MARIA (F):",
          sum(p["frequencia"] for p in dados[0]["res"]) if dados else "sem resposta")


def baixar_evento(venue):
    registros, deslocamento = [], 0
    consulta = urllib.parse.quote(f"stream:streams/conf/{venue}:")
    while True:
        url = f"{DBLP}?q={consulta}&h=1000&f={deslocamento}&format=json"
        dados = obter_json(url)
        if not dados:
            break
        hits = dados["result"]["hits"]
        lote = hits.get("hit", [])
        if not lote:
            break
        registros += [h["info"] for h in lote]
        deslocamento += len(lote)
        if deslocamento >= int(hits["@total"]):
            break
        time.sleep(1)
    return registros


def limpar_nome(nome):
    return re.sub(r"\s\d{4}$", "", nome).strip()


def artigos_do_evento(venue, ano_min, ano_max):
    vistos, artigos = set(), []
    for info in baixar_evento(venue):
        if info.get("type") != "Conference and Workshop Papers":
            continue  
        chave = info.get("key")
        if chave in vistos or "authors" not in info:
            continue
        try:
            ano = int(info["year"])
        except (KeyError, ValueError):
            continue
        if not ano_min <= ano <= ano_max:
            continue
        autores = info["authors"]["author"]
        if isinstance(autores, dict):
            autores = [autores]
        vistos.add(chave)
        artigos.append(
            {
                "venue": venue,
                "chave": chave,
                "ano": ano,
                "titulo": info.get("title", ""),
                "autores": [limpar_nome(a["text"]) for a in autores],
            }
        )
    return artigos


def primeiro_nome(nome):
    partes = nome.split()
    if not partes:
        return ""
    token = unicodedata.normalize("NFKD", partes[0]).encode("ascii", "ignore").decode()
    token = re.sub(r"[^A-Za-z]", "", token).upper()
    return token if len(token) >= 2 else ""  


class ClassificadorIBGE:
    def __init__(self, arquivo_cache, limiar):
        self.arquivo = Path(arquivo_cache)
        self.limiar = limiar
        self.cache = json.loads(self.arquivo.read_text()) if self.arquivo.exists() else {}

    def _frequencia(self, nome, sexo):
        dados = obter_json(IBGE.format(nome=urllib.parse.quote(nome), sexo=sexo))
        if dados is None:
            return None
        if not dados:
            return 0 
        return sum(p["frequencia"] for p in dados[0].get("res", []))

    def _buscar(self, nome):
        f, m = self._frequencia(nome, "F"), self._frequencia(nome, "M")
        return None if f is None or m is None else {"F": f, "M": m}

    def pre_carregar(self, nomes, trabalhadores=6):
        from concurrent.futures import ThreadPoolExecutor
        faltam = [n for n in sorted(set(nomes)) if n and n not in self.cache]
        if not faltam:
            return
        print(f"       consultando o IBGE para {len(faltam)} primeiros nomes distintos ...", flush=True)
        falhas = 0
        with ThreadPoolExecutor(max_workers=trabalhadores) as ex:
            for i, (nome, c) in enumerate(zip(faltam, ex.map(self._buscar, faltam)), 1):
                if c is None:
                    falhas += 1
                else:
                    self.cache[nome] = c
                if i % 200 == 0:
                    print(f"       ... {i}/{len(faltam)} nomes consultados", flush=True)
                    self.salvar()
        self.salvar()
        if falhas:
            print(f"[aviso] {falhas} nomes falharam e NÃO foram classificados; "
                  "rode de novo para tentar outra vez (os demais ficam no cache).", file=sys.stderr)

    def contagens(self, nome):
        if nome not in self.cache:
            c = self._buscar(nome)
            if c is None:
                return {"F": 0, "M": 0}  
            self.cache[nome] = c
        return self.cache[nome]

    def classificar(self, nome):
        if not nome:
            return "U"
        c = self.contagens(nome)
        total = c["F"] + c["M"]
        if total == 0:
            return "U"
        prop_f = c["F"] / total
        if prop_f >= self.limiar:
            return "F"
        if prop_f <= 1 - self.limiar:
            return "M"
        return "A"

    def salvar(self):
        self.arquivo.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0))


def estatisticas(linhas):
    artigos = defaultdict(list)
    for l in linhas:
        artigos[l["chave"]].append(l)
    n_f = sum(l["genero"] == "F" for l in linhas)
    n_m = sum(l["genero"] == "M" for l in linhas)
    classificadas = n_f + n_m

    com_classificada = [a for a in artigos.values() if any(l["genero"] in "FM" for l in a)]
    com_mulher = [a for a in com_classificada if any(l["genero"] == "F" for l in a)]
    primeiras = [min(a, key=lambda l: l["pos"]) for a in artigos.values()]
    primeiras = [p for p in primeiras if p["genero"] in ("F", "M")]
    primeiras_f = [p for p in primeiras if p["genero"] == "F"]

    def pct(a, b):
        return round(100 * a / b, 1) if b else None

    return {
        "artigos": len(artigos),
        "autorias": len(linhas),
        "cobertura_pct": pct(classificadas, len(linhas)),
        "mulheres_pct": pct(n_f, classificadas),
        "artigos_com_mulher_pct": pct(len(com_mulher), len(com_classificada)),
        "primeira_autora_pct": pct(len(primeiras_f), len(primeiras)),
    }


def agrupar(linhas, chave):
    grupos = defaultdict(list)
    for l in linhas:
        grupos[(l["venue"], chave(l))].append(l)
    return grupos


def rotulo_periodo(ano, ano_min, janela, ano_max=None):
    inicio = ano_min + ((ano - ano_min) // janela) * janela
    fim = inicio + janela - 1
    if ano_max is not None:
        fim = min(fim, ano_max)
    return f"{inicio}" if inicio == fim else f"{inicio}--{fim}"


def salvar_csv(caminho, linhas, campos):
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(linhas)


def formatar(valor):
    return "--" if valor is None else str(valor).replace(".", ",")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--venues", nargs="+", default=["sbseg", "sbrc"],
                    help="caminho do evento no SOL (sol.sbc.org.br/index.php/<chave>) ou "
                         "conf/<chave> no DBLP; o primeiro é o evento principal")
    ap.add_argument("--fonte", choices=["sol", "dblp"], default="sol")
    ap.add_argument("--min-paginas", type=int, default=0,
                    help="descarta artigos com menos de N páginas (análise de sensibilidade; "
                         "páginas desconhecidas são mantidas). Use --saida diferente para não "
                         "sobrescrever os resultados principais")
    ap.add_argument("--refazer", action="store_true",
                    help="ignora o cache local e baixa os registros do SOL de novo")
    ap.add_argument("--diagnostico", action="store_true",
                    help="só testa a conexão com o SOL e o IBGE e mostra o resultado")
    ap.add_argument("--ano-min", type=int, default=2001)
    ap.add_argument("--ano-max", type=int, default=2025)
    ap.add_argument("--janela", type=int, default=5, help="tamanho do período (anos) na tabela")
    ap.add_argument("--limiar", type=float, default=0.9,
                    help="proporção mínima de um sexo para classificar o nome (padrão 0,9)")
    ap.add_argument("--saida", default="saida")
    args = ap.parse_args()
    print(f"coleta_sbseg.py versão {VERSAO}")
    if args.diagnostico:
        diagnosticar(args.venues)
        return

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    CACHE["pasta"], CACHE["refazer"] = saida, args.refazer
    FILTROS["min_paginas"] = args.min_paginas
    clf = ClassificadorIBGE(saida / "cache_ibge.json", args.limiar)

    linhas, todos_artigos = [], []
    buscar = artigos_do_evento_sol if args.fonte == "sol" else artigos_do_evento
    for venue in args.venues:
        print(f"[{args.fonte}] baixando {venue} ...")
        artigos = buscar(venue, args.ano_min, args.ano_max)
        print(f"       {len(artigos)} artigos em {args.ano_min}-{args.ano_max}")
        if not artigos:
            print(f"[aviso] nenhum artigo para '{venue}'. Confira a chave do evento e a conexão.",
                  file=sys.stderr)
        print("       por ano:", dict(sorted(Counter(a["ano"] for a in artigos).items())))
        clf.pre_carregar(primeiro_nome(n) for art in artigos for n in art["autores"])
        for art in artigos:
            todos_artigos.append({k: art.get(k, "") for k in
                                  ("venue", "chave", "ano", "titulo", "tipo", "fonte")})
            for pos, nome in enumerate(art["autores"]):
                pn = primeiro_nome(nome)
                linhas.append({
                    "venue": venue, "chave": art["chave"], "ano": art["ano"],
                    "pos": pos, "nome": nome, "primeiro_nome": pn,
                    "genero": clf.classificar(pn),
                })
        clf.salvar()

    if not linhas:
        sys.exit("Nenhum dado coletado; nada a analisar.")
    salvar_csv(saida / "artigos.csv", todos_artigos,
               ["venue", "chave", "ano", "titulo", "tipo", "fonte"])
    salvar_csv(saida / "autorias.csv", linhas,
               ["venue", "chave", "ano", "pos", "nome", "primeiro_nome", "genero"])

    campos = ["venue", "grupo", "artigos", "autorias", "cobertura_pct",
              "mulheres_pct", "artigos_com_mulher_pct", "primeira_autora_pct"]

    por_ano = [{"venue": v, "grupo": a, **estatisticas(l)}
               for (v, a), l in sorted(agrupar(linhas, lambda x: x["ano"]).items())]
    salvar_csv(saida / "resumo_por_ano.csv", por_ano, campos)

    por_periodo = [{"venue": v, "grupo": p, **estatisticas(l)}
                   for (v, p), l in sorted(agrupar(
                       linhas, lambda x: rotulo_periodo(x["ano"], args.ano_min, args.janela,
                                                        args.ano_max)).items())]
    salvar_csv(saida / "resumo_por_periodo.csv", por_periodo, campos)

    principal = args.venues[0]
    with open(saida / "tabela_periodos.tex", "w", encoding="utf-8") as f:
        for r in por_periodo:
            if r["venue"] == principal:
                f.write(" & ".join([
                    r["grupo"], str(r["artigos"]), str(r["autorias"]),
                    formatar(r["mulheres_pct"]), formatar(r["artigos_com_mulher_pct"]),
                    formatar(r["primeira_autora_pct"]),
                ]) + " \\\\\n")

    print("\n=== Totais ===")
    for v in args.venues:
        l = [x for x in linhas if x["venue"] == v]
        if l:
            e = estatisticas(l)
            print(v, e)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[aviso] matplotlib não instalado; figura não gerada (pip install matplotlib)")
        return
    (saida / "figures").mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 3))
    for v in args.venues:
        pts = [(r["grupo"], r["mulheres_pct"]) for r in por_ano
               if r["venue"] == v and r["mulheres_pct"] is not None]
        if pts:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", label=v.upper(),
                    color=COR_MULHERES if v == args.venues[0] else None)
    ax.set_xlabel("Edição (ano)")
    ax.set_ylabel("Mulheres entre autorias\nclassificadas (%)")
    ax.set_ylim(0, 30)
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(saida / "figures" / "mulheres_por_ano.png", dpi=200)
    print("\nArquivos gerados em", saida.resolve())


if __name__ == "__main__":
    main()
