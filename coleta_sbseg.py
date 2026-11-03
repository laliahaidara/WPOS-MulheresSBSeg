#!/usr/bin/env python3
"""
Participação feminina nos anais do SBSeg (e de um evento de referência).

Fluxo:
  1. Baixa os metadados de artigos de cada evento na API pública do DBLP.
  2. Extrai o primeiro nome de cada autor(a) e consulta a API de Nomes do
     Censo (IBGE) para estimar o gênero com base nas frequências por sexo.
  3. Calcula as métricas por edição e por período e salva CSVs, uma figura
     e as linhas de tabela prontas para o LaTeX.

Uso (no seu computador, com internet):
    python3 coleta_sbseg.py
    python3 coleta_sbseg.py --venues sbseg sbrc --ano-min 2001 --ano-max 2025

Só usa a biblioteca padrão; a figura exige matplotlib (pip install matplotlib).
A primeira execução leva alguns minutos por causa das consultas ao IBGE; os
resultados ficam em cache (saida/cache_ibge.json) e as próximas são rápidas.
"""
import argparse
import csv
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

DBLP = "https://dblp.org/search/publ/api"
IBGE = "https://servicodados.ibge.gov.br/api/v2/censos/nomes/{nome}?sexo={sexo}"
CABECALHO = {"User-Agent": "estudo-genero-wpos/1.0 (pesquisa academica)"}


def obter_json(url, tentativas=4, pausa=2.0):
    ultimo_erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers=CABECALHO)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as erro:  # rede, 429, JSON inválido
            ultimo_erro = erro
            time.sleep(pausa * (i + 1))
    print(f"[aviso] falha em {url}: {ultimo_erro}", file=sys.stderr)
    return None


# ----------------------------------------------------------------- DBLP
def baixar_evento(venue):
    """Retorna a lista de registros ('info') do DBLP para conf/<venue>."""
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
    """Remove o sufixo numérico de desambiguação do DBLP (ex.: 'Ana Silva 0002')."""
    return re.sub(r"\s\d{4}$", "", nome).strip()


def artigos_do_evento(venue, ano_min, ano_max):
    vistos, artigos = set(), []
    for info in baixar_evento(venue):
        if info.get("type") != "Conference and Workshop Papers":
            continue  # descarta prefácios/editoriais (tipo 'Editorship')
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


# ---------------------------------------------------------------- Gênero
def primeiro_nome(nome):
    partes = nome.split()
    if not partes:
        return ""
    token = unicodedata.normalize("NFKD", partes[0]).encode("ascii", "ignore").decode()
    token = re.sub(r"[^A-Za-z]", "", token).upper()
    return token if len(token) >= 2 else ""  # iniciais ('J.') ficam sem classificação


class ClassificadorIBGE:
    def __init__(self, arquivo_cache, limiar):
        self.arquivo = Path(arquivo_cache)
        self.limiar = limiar
        self.cache = json.loads(self.arquivo.read_text()) if self.arquivo.exists() else {}

    def _frequencia(self, nome, sexo):
        dados = obter_json(IBGE.format(nome=urllib.parse.quote(nome), sexo=sexo))
        if not dados:
            return 0
        return sum(p["frequencia"] for p in dados[0].get("res", []))

    def contagens(self, nome):
        if nome not in self.cache:
            self.cache[nome] = {
                "F": self._frequencia(nome, "F"),
                "M": self._frequencia(nome, "M"),
            }
            time.sleep(0.2)
        return self.cache[nome]

    def classificar(self, nome):
        """Retorna 'F', 'M', 'A' (ambíguo) ou 'U' (sem informação)."""
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


# ------------------------------------------------------------- Estatística
def estatisticas(linhas):
    """Métricas para um conjunto de autorias (um evento em um ano ou período)."""
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


def rotulo_periodo(ano, ano_min, janela):
    inicio = ano_min + ((ano - ano_min) // janela) * janela
    return f"{inicio}--{inicio + janela - 1}"


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
                    help="chaves do DBLP em conf/<chave>; o primeiro é o evento principal")
    ap.add_argument("--ano-min", type=int, default=2001)
    ap.add_argument("--ano-max", type=int, default=2025)
    ap.add_argument("--janela", type=int, default=5, help="tamanho do período (anos) na tabela")
    ap.add_argument("--limiar", type=float, default=0.9,
                    help="proporção mínima de um sexo para classificar o nome (padrão 0,9)")
    ap.add_argument("--saida", default="saida")
    args = ap.parse_args()

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    clf = ClassificadorIBGE(saida / "cache_ibge.json", args.limiar)

    linhas = []
    for venue in args.venues:
        print(f"[dblp] baixando {venue} ...")
        artigos = artigos_do_evento(venue, args.ano_min, args.ano_max)
        print(f"       {len(artigos)} artigos em {args.ano_min}-{args.ano_max}")
        for art in artigos:
            for pos, nome in enumerate(art["autores"]):
                pn = primeiro_nome(nome)
                linhas.append({
                    "venue": venue, "chave": art["chave"], "ano": art["ano"],
                    "pos": pos, "nome": nome, "primeiro_nome": pn,
                    "genero": clf.classificar(pn),
                })
        clf.salvar()

    salvar_csv(saida / "autorias.csv", linhas,
               ["venue", "chave", "ano", "pos", "nome", "primeiro_nome", "genero"])

    campos = ["venue", "grupo", "artigos", "autorias", "cobertura_pct",
              "mulheres_pct", "artigos_com_mulher_pct", "primeira_autora_pct"]

    por_ano = [{"venue": v, "grupo": a, **estatisticas(l)}
               for (v, a), l in sorted(agrupar(linhas, lambda x: x["ano"]).items())]
    salvar_csv(saida / "resumo_por_ano.csv", por_ano, campos)

    por_periodo = [{"venue": v, "grupo": p, **estatisticas(l)}
                   for (v, p), l in sorted(agrupar(
                       linhas, lambda x: rotulo_periodo(x["ano"], args.ano_min, args.janela)).items())]
    salvar_csv(saida / "resumo_por_periodo.csv", por_periodo, campos)

    # Linhas de tabela LaTeX para o evento principal (usadas via \input no artigo)
    principal = args.venues[0]
    with open(saida / "tabela_periodos.tex", "w", encoding="utf-8") as f:
        for r in por_periodo:
            if r["venue"] == principal:
                f.write(" & ".join([
                    r["grupo"], str(r["artigos"]), str(r["autorias"]),
                    formatar(r["mulheres_pct"]), formatar(r["artigos_com_mulher_pct"]),
                    formatar(r["primeira_autora_pct"]),
                ]) + " \\\\\n")

    # Totais gerais (úteis para o texto)
    print("\n=== Totais ===")
    for v in args.venues:
        l = [x for x in linhas if x["venue"] == v]
        if l:
            e = estatisticas(l)
            print(v, e)

    # Figura
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
            ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", label=v.upper())
    ax.set_xlabel("Edição (ano)")
    ax.set_ylabel("Mulheres entre autorias\nclassificadas (%)")
    ax.set_ylim(0, 50)
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(saida / "figures" / "mulheres_por_ano.png", dpi=200)
    print("\nArquivos gerados em", saida.resolve())


if __name__ == "__main__":
    main()
