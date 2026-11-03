# Participação feminina nos anais do SBSeg

Código e resultados agregados do artigo **"Participação feminina nos anais do SBSeg: uma análise bibliométrica por edição"**, de Lalia Sadio e Maristela Holanda (Universidade de Brasília), preparado para o 21º Workshop de Graduação e Pós-Graduação do CIC/UnB (WPOS 2026).

O estudo mede a participação de mulheres na autoria dos artigos do Simpósio Brasileiro de Cibersegurança (SBSeg), edição por edição, de 2001 a 2026. Os metadados vêm do repositório SBC OpenLib (SOL), e o gênero é inferido pelo primeiro nome com as frequências do Censo (IBGE).

## Resultados principais

926 artigos e 3.225 autorias em 26 edições (2001–2026). Foram classificadas pelo primeiro nome 95,3% das autorias. Todos os percentuais abaixo consideram só as autorias classificadas.

| Período | Artigos | Autorias | % mulheres | % artigos com ≥1 mulher | % 1ª autora |
|---|---:|---:|---:|---:|---:|
| 2001–2005 | 113 | 318 | 6,6 | 17,7 | 2,7 |
| 2006–2010 | 104 | 316 | 12,5 | 30,0 | 9,0 |
| 2011–2015 | 147 | 498 | 15,4 | 43,2 | 18,2 |
| 2016–2020 | 196 | 645 | 9,3 | 24,5 | 7,8 |
| 2021–2025 | 264 | 1076 | 9,2 | 28,4 | 11,4 |
| 2026 (uma edição) | 102 | 372 | 13,1 | 33,3 | 16,3 |
| **Total** | **926** | **3225** | **10,7** | **29,3** | **10,9** |

A figura `saida/figures/mulheres_por_ano.png` mostra o percentual de mulheres por edição.

## Como funciona

1. **Coleta.** Baixa os metadados dos artigos (título, autores, data) do SOL pelo protocolo OAI-PMH (`https://sol.sbc.org.br/index.php/sbseg/oai`). Prefácios e itens que não são artigos são descartados, e a ordem de autoria é preservada.
2. **Inferência de gênero.** Consulta o primeiro nome de cada autor(a) na API de Nomes do Censo do IBGE. Com `p_F = f_F / (f_F + f_M)`, a autoria é classificada como feminina se `p_F ≥ 0,9`, masculina se `p_F ≤ 0,1` e ambígua nos demais casos. Nomes ausentes na base e iniciais ficam sem classificação. O limiar de 0,9 é o mesmo de Dal Pizzol et al. (WIT 2022).
3. **Métricas.** Por edição e por período de cinco anos: (i) % de mulheres entre as autorias classificadas; (ii) % de artigos com ao menos uma autora; (iii) % de artigos cuja primeira autoria é feminina. A cobertura (proporção de autorias classificadas) é sempre registrada.

## Como reproduzir

Requer Python 3.8 ou superior e acesso à internet. O script usa só a biblioteca padrão; a figura exige `matplotlib`.

```bash
pip install matplotlib   # opcional, só para a figura
python3 coleta_sbseg.py --venues sbseg --ano-max 2026
```

Atenção: sem esses parâmetros, o script usa `--ano-max 2025` e coleta também o SBRC.

A primeira execução leva alguns minutos por causa das consultas ao IBGE. Os resultados ficam em cache dentro de `saida/`, e as execuções seguintes são rápidas. O SOL recebe novas edições e correções com o tempo, então uma coleta futura pode dar números um pouco diferentes dos do artigo, que correspondem à coleta feita em 2026.

Opções úteis:

| Opção | O que faz |
|---|---|
| `--venues` | evento(s) no SOL (`sol.sbc.org.br/index.php/<chave>`); o primeiro é o principal |
| `--ano-min`, `--ano-max` | intervalo de edições (padrão 2001 a 2025) |
| `--janela` | tamanho do período da tabela, em anos (padrão 5) |
| `--limiar` | proporção mínima de um sexo para classificar o nome (padrão 0,9) |
| `--min-paginas N` | descarta artigos com menos de N páginas (análise de sensibilidade; use outro `--saida`) |
| `--refazer` | ignora o cache local e baixa os registros do SOL de novo |
| `--diagnostico` | só testa a conexão com o SOL e o IBGE |
| `--saida` | pasta de saída (padrão `saida`) |

Ao rodar, o script imprime a versão (`coleta_sbseg.py versão ...`) e a contagem de artigos por ano. Confira essa contagem com o sumário de cada edição.

## Arquivos

```
coleta_sbseg.py            script de coleta, inferência e análise
saida/
  resumo_por_ano.csv       métricas por edição
  resumo_por_periodo.csv   métricas por período de cinco anos
  artigos.csv              lista de artigos (venue, URL no SOL, ano, título, tipo, fonte)
  tabela_periodos.tex      linhas da tabela do artigo (LaTeX)
  figures/mulheres_por_ano.png
```

O script também gera, na pasta `saida/`, os arquivos `autorias.csv`, `oai_sbseg.json` e `cache_ibge.json`. Eles **não são versionados** (veja `.gitignore`):

- `autorias.csv` lista cada pessoa com o gênero inferido. Não é divulgado para evitar a exposição individual.
- `oai_sbseg.json` (metadados brutos do SOL) e `cache_ibge.json` (frequências do IBGE) são dados públicos que o próprio script baixa de novo.

## Limitações

- O gênero é **inferido pelo nome**, e não autodeclarado, e as categorias binárias não representam a identidade das pessoas. Nomes unissex, nomes estrangeiros e pessoas cujo nome não corresponde ao seu gênero podem ser classificados de forma incorreta.
- Os resultados refletem as autorias classificadas (95,3% do total), e não todas.
- Autoria não equivale a participação: papéis em comitês, palestras e organização não são cobertos.
- Só os anais principais do SBSeg foram analisados, sem os anais estendidos.

Mais detalhes, incluindo as análises de sensibilidade, estão na seção "Ameaças à validade" do artigo.

## Ética

Foram usados apenas metadados bibliográficos públicos, apresentados de forma agregada. A justificativa sobre a avaliação pelo sistema CEP/CONEP está na seção "Ética e reprodutibilidade" do artigo.

## Como citar

> SADIO, L.; HOLANDA, M. Participação feminina nos anais do SBSeg: uma análise bibliométrica por edição. In: Workshop de Graduação e Pós-Graduação do CIC/UnB (WPOS), 21., 2026, Brasília. Universidade de Brasília, 2026.

Código e resultados: <https://github.com/laliahaidara/WPOS>
