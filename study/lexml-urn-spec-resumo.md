# LexML & URN LEX — Resumo para o projeto RAG

> **Documento de referência** para o Dia 1 do plano de 4 semanas.
> Cobre: por que o LexML existe, hist贸ria, especificação URN LEX, e implicações práticas para chunking, IDs estáveis e verificação de citação.

---

## 1. Por que o LexML existe — o problema que ele resolve

O direito brasileiro é fragmentado numa escala que a maioria dos países não enfrenta. Entre as décadas de 1980 e o final dos anos 2000, o sistema acumulou:

- **~150 mil normas federais** (média de 21 normas/dia)
- **~1 milhão de normas estaduais** distribuídas entre 27 estados (média de 135/dia)
- **~2,6 milhões de normas municipais** entre quase 5.700 municípios (média de 360/dia)

Cada Poder (Executivo, Legislativo, Judiciário) e cada nível (federal, estadual, municipal) construiu sistemas independentes desde os anos 1970, sem preocupação com interoperabilidade. O resultado: legado digital disperso, identificadores inconsistentes, formatos incompatíveis.

A pressão constitucional sempre foi real:

- **Art. 5º, LXXIV** — direito de acesso à informação
- **Art. 37, caput** — princípio da publicidade da administração pública
- **Art. 216, §2º** — gestão e franquia da documentação governamental
- **Princípio do _ignorantia legis neminem excusat_** — implícito em todo o ordenamento

A **Lei de Acesso à Informação (Lei nº 12.527/2011, em vigor desde maio de 2012)** deu efetividade operacional a esses princípios e fortaleceu o papel do LexML como instrumento de transparência.

---

## 2. Como começou — história em marcos

| Ano | Marco |
|---|---|
| 1997 | Primeira modelagem acadêmica da estrutura de documentos legislativos brasileiros em XML |
| ~2000 | Exploração inicial de XML para documentos legislativos no PRODASEN (Senado Federal) |
| Nov 2005 | Projeto nomeado oficialmente "LexML Brasil" durante a X ENIAL |
| 2006 | Formação do grupo de trabalho com Senado, Câmara, STF e Ministério da Justiça |
| **30 jun 2009** | **Lançamento oficial do portal LexML** com 1,28 milhão de documentos indexados |
| 2009 | LexML incorporado ao e-PING (Padrões de Interoperabilidade do Governo Federal) |
| Set 2010 | Acervo ultrapassa 1,5 milhão de documentos |
| 2012 | Lei de Acesso à Informação entra em vigor e reforça o papel institucional do portal |
| 2022 | `urn:lex` adicionado oficialmente à lista IANA de "Formal URN Namespaces" |
| **Mai 2025** | **Publicação da RFC 9676** (informacional) finalizando a especificação URN LEX |

O modelo foi o projeto italiano **Norme in Rete**. Países de tradição civil-law enfrentam problemas estruturalmente semelhantes, então o Brasil pegou emprestado deliberadamente em vez de reinventar. A Itália e o Brasil são, até hoje, os dois maiores adotantes da URN LEX.

---

## 3. LexML-BR são 4 padrões, não um

Quando se fala "LexML" normalmente é solto. Tecnicamente é uma stack:

| Padrão | Conteúdo |
|---|---|
| **LexML-BR Parte 1** | Arquitetura geral e governança |
| **LexML-BR Parte 2** | Esquema **URN LEX** para nomeação e referência de normas |
| **LexML-BR Parte 3** | **XML Schema** para texto completo de leis, conforme a LCP-95 |
| **LexML-BR Parte 4** | Protocolo **OAI-PMH** para troca e centralização de metadados |

Para o seu RAG, **Parte 2 (URN) e Parte 3 (hierarquia XML) são as duas que importam**.

---

## 4. O namespace URN LEX — anatomia

### Estrutura geral

```
urn:lex:<jurisdição>:<nome-local>[~<id-de-partição>]
```

### `<jurisdição>` — onde a lei foi emitida

Código do país, com unidade opcional separada por `;`:

| Exemplo | Significado |
|---|---|
| `br` | Federal |
| `br;sao.paulo` | Estado de São Paulo |
| `br;minas.gerais` | Estado de Minas Gerais |
| `br;sao.paulo;sao.paulo` | Município de São Paulo |
| `br;rio.de.janeiro;rio.de.janeiro` | Município do Rio de Janeiro |

### `<nome-local>` — qual lei, exatamente

Estruturado como `<autoridade>:<tipo>:<data>;<número>`:

- **Autoridade**: `federal`, `estadual`, `municipal`, ou órgão específico (`anpd`, `cgi.br`, etc.)
- **Tipo**: `lei`, `lei.complementar`, `decreto`, `medida.provisoria`, `constituicao`, `resolucao`, `portaria`, `instrucao.normativa`, etc.
- **Data**: formato ISO `YYYY-MM-DD`
- **Número**: o número oficial do ato

### `<id-de-partição>` (opcional) — qual pedaço do documento

Endereçamento hierárquico, separado por `;`:

| Partição | Significa |
|---|---|
| `art7` | Artigo 7º |
| `art7;par1` | §1º do art. 7º |
| `art7;par1;inc2` | Inciso II do §1º do art. 7º |
| `art7;par1;inc2;ali-a` | Alínea "a" do inciso II do §1º do art. 7º |
| `art7;cpt` | Caput do art. 7º (algumas implementações) |

---

## 5. O separador `~` importa (e por quê)

Pergunta natural: por que `~` e não `#`?

Em URIs, o caractere `#` é tratado pelo navegador como _fragment_ — **e fragmentos não são transmitidos ao servidor**. Isso quebra o caso de uso principal de uma URN LEX: pedir só uma parte de um documento longo (um único artigo dentro de um código de 800 artigos) e fazer o resolver retornar apenas essa parte.

A solução do RFC 9676 foi adotar `~` como separador de partição. Por ser um caractere "normal" no path da URN, ele é transmitido ao servidor — o resolver pode então decidir retornar só o pedaço pedido. Internamente, o resolver depois transforma `~partition` em `#partition` no URL HTML retornado, para que o navegador role até a posição correta na página.

**Implicação prática para o RAG:** seus IDs de chunk devem usar `~` quando armazenados/referenciados como URN LEX completa. Se preferir armazenar apenas o partition ID (`art7;par1`) separadamente do URN do documento, é igualmente válido — só não confunda com `#` em nenhum momento.

---

## 6. Exemplos práticos para o seu corpus

| Documento | URN LEX |
|---|---|
| LGPD (lei inteira) | `urn:lex:br:federal:lei:2018-08-14;13709` |
| LGPD Art. 7º | `urn:lex:br:federal:lei:2018-08-14;13709~art7` |
| LGPD Art. 7º, §1º | `urn:lex:br:federal:lei:2018-08-14;13709~art7;par1` |
| LGPD Art. 18, I | `urn:lex:br:federal:lei:2018-08-14;13709~art18;inc1` |
| Marco Civil da Internet | `urn:lex:br:federal:lei:2014-04-23;12965` |
| Marco Civil Art. 7º, VII | `urn:lex:br:federal:lei:2014-04-23;12965~art7;inc7` |
| Lei Carolina Dieckmann | `urn:lex:br:federal:lei:2012-11-30;12737` |
| Lei do Software | `urn:lex:br:federal:lei:1998-02-19;9609` |
| Lei 14.155/21 (crimes cibernéticos) | `urn:lex:br:federal:lei:2021-05-27;14155` |
| Constituição Federal | `urn:lex:br:federal:constituicao:1988-10-05;1988` |
| LCP-95 (técnica legislativa) | `urn:lex:br:federal:lei.complementar:1998-02-26;95` |
| Decreto 8.771/16 (regulamenta Marco Civil) | `urn:lex:br:federal:decreto:2016-05-11;8771` |

**Teste rápido:** prefixe qualquer um com `https://www.lexml.gov.br/urn/` e abra no navegador. O resolver retorna a página canônica do documento.

---

## 7. Por que isso é decisivo para o RAG

### 7.1 IDs estáveis e citáveis

A maioria dos RAGs usa UUIDs aleatórios ou hashes de conteúdo como ID de chunk. Com URN LEX:

- ID é **determinístico** — a mesma lei sempre gera o mesmo URN
- ID é **legível por humanos** — "art. 18, I da LGPD" em vez de "doc_a3f9b21"
- ID **sobrevive a reindexação** — não muda com troca de modelo de embedding ou rechunking
- ID **é citação jurídica válida** — pode ir direto na UI sem transformação

### 7.2 Estratégia de chunking emerge da LCP-95

A **Lei Complementar 95/1998** define a hierarquia padrão de toda lei federal brasileira:

```
artigo (art)
  └─ parágrafo (par) — incluindo o caput
      └─ inciso (inc) — em algarismos romanos: I, II, III...
          └─ alínea (ali) — em letra minúscula: a, b, c...
              └─ item — em algarismos arábicos: 1, 2, 3...
```

**Seu parser não deve inventar fronteiras** — ele deve respeitar essa hierarquia. O `RecursiveCharacterTextSplitter` padrão de qualquer framework vai cortar artigos no meio, separar inciso do parágrafo correspondente, e destruir contexto jurídico. Inaceitável para um RAG sério.

A convenção de partição do URN LEX (`art7;par1;inc2;ali-a`) mapeia **1:1** com essa hierarquia. Resultado: **seu chunk ID vira simultaneamente a citação jurídica e a chave primária no banco de dados vetorial**.

### 7.3 Verificação de citação fica barata e exata

Como o ID de partição codifica a posição estrutural exata, verificar uma citação gerada pelo LLM exige duas operações triviais:

1. Parse do URN de partição retornado pelo LLM
2. Confirmar que a quote citada existe no chunk com aquele partition ID

Sem fuzzy matching. Sem heurísticas. Match exato ou rejeita com flag `verified: false`.

### 7.4 Resolução de fonte oficial gratuita

Para qualquer URN no seu output, você pode gerar um link "ver fonte oficial":

```
https://www.lexml.gov.br/urn/<URN>
```

Isso é detalhe de portfólio que separa o sério do tutorial — toda citação tem link para o documento canônico no portal do governo, sem você precisar manter mapeamento próprio.

---

## 8. Leituras prioritárias para o Dia 1

Em ordem de prioridade:

1. **RFC 9676 — LEX URN namespace spec.**
   Skim das seções 1–3 e 5; aprofundar na sintaxe de partição (seção 5).
   https://datatracker.ietf.org/doc/rfc9676/

2. **LCP-95 (Lei Complementar 95/1998).**
   A lei que define como leis são escritas. Curta e concreta — leia inteira.
   https://www.lexml.gov.br/urn/urn:lex:br:federal:lei.complementar:1998-02-26;95

3. **História do projeto LexML.**
   Contexto institucional e motivação política.
   https://projeto.lexml.gov.br/institucional/historia

4. **Uma página real do Planalto da LGPD.**
   Abrir com `view-source:` e anotar classes CSS, estrutura HTML, ids de âncora. É exatamente isso que seu parser vai consumir.
   http://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm

---

## 9. Questões em aberto — investigadas

Cada item foi confirmado pela RFC 9676 e/ou por exemplos reais no catálogo `lexml.gov.br`. Onde não há exemplo indexado direto, marco como **conjectura** com a convenção observada.

- [x] **Como o LexML lida com _"redação dada pela Lei X"_? Mesma URN com componente de versão (`@`), ou URN distinta?**
  → **Mesma URN da obra, com `@<data>` indicando a expressão.** A RFC 9676 §5.3 define `local-name = work ["@" expression] ["$" manifestation]`. A "obra" (a lei como entidade abstrata e perene) tem URN estável; cada redação histórica é uma _expressão_ identificada pela data da última emenda incorporada. O texto original tem o token reservado `@original`. Modelo FRBR-inspirado (work / expression / manifestation / item).
  - Exemplo: `urn:lex:br:federal:lei:2018-08-14;13709` (a LGPD como obra) vs. `urn:lex:br:federal:lei:2018-08-14;13709@2023-05-10` (redação vigente em 10/05/2023).
  - **Implicação para o RAG:** ao indexar, decida se vai armazenar uma expressão fixa (snapshot temporal) ou seguir a versão consolidada. Se for a vigente, considere reindexar quando houver alteração — o ID da obra não muda, mas o conteúdo do chunk pode.
  - _Fonte: RFC 9676, §§5.3, 7.1._

- [x] **Artigos revogados continuam endereçáveis por URN?**
  → **Sim — confirmado.** A URN identifica a obra; revogação é metadado da expressão. Um artigo revogado mantém URN estável (`...~art45`) e o resolver pode retornar tanto a versão atual (em geral com nota "Revogado pela Lei X") quanto qualquer expressão histórica via `@<data>`. A RFC 9676 §7.1.2 prevê tanto estratégias "multi-version" (um único objeto com marcação textual de versões) quanto "single-version" (objetos separados por data), mas em ambos a URN da obra é invariante.
  - **Implicação para o RAG:** preservar chunks de dispositivos revogados é útil — o usuário pode citar uma decisão antiga que se refere ao artigo na redação revogada. Marque-os com metadado de status; não os exclua do índice.
  - _Fonte: RFC 9676, §7.1._

- [x] **A ANPD tem código de autoridade reconhecido na URN, ou suas resoluções resolvem sob `federal:resolucao`?**
  → **DECIDIDO em Phase 4.3.a (2026-05-15): autoridade `autoridade.nacional.protecao.dados`, tipo `resolucao.cd`.**
  - Forma canônica: `urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:YYYY-MM-DD;N`
  - O sufixo `.cd` no tipo (Conselho Diretor) espelha o cabeçalho oficial dos atos
    ("RESOLUÇÃO CD/ANPD Nº 15, DE 24 DE ABRIL DE 2024") e mantém espaço pra outros
    tipos de ato ANPD no futuro (Diretoria, Coordenação-Geral, etc.) sem colisão.
  - **Diferença vs convenção CNJ/STF**: outros órgãos usam só `resolucao` porque
    todas as resoluções saem do plenário/CD. ANPD é mais novo e ainda está
    estabelecendo padrões institucionais; explicitar `.cd` é defensivo.
  - Exemplos canônicos:
    - Res. 15/2024 (Comunicação de Incidente): `urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2024-04-24;15`
    - Res. 4/2023 (Dosimetria): `urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2023-02-24;4`
    - Res. 2/2022 (Pequeno Porte): `urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2022-01-27;2`
    - Res. 1/2021 (Fiscalização): `urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2021-10-28;1`
  - O resolver `lexml.gov.br/urn/` retorna 404 pra essas URNs (catálogo oficial
    ainda não cobre ANPD). É esperado e foi flagado nas notas técnicas da própria
    ANPD ao Senado. Fallback prático: `gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd`.
  - **Implicação produção**: nossas URNs ANPD são CANÔNICAS DO LADO DO PROJETO
    até o LexML oficial alcançar. Documentação clara em answer + footer
    explicando o status sintético resolve a questão de transparência.
  - _Fonte: Phase 4.3.a transcription, 2026-05-15; convenção LexML observada;
    cabeçalho oficial DOU dos atos ANPD._

- [x] **Como decretos regulamentadores (ex.: Decreto 8.771/16 do Marco Civil) se relacionam à URN da lei-mãe?**
  → **Não há componente de relação na URN.** A sintaxe URN LEX (RFC 9676 §5) tem apenas dois separadores semânticos além do _work_: `@` (expressão/versão) e `$` (manifestação/formato). Não existe `>` ou similar para "regulamenta", "revoga" ou "altera". O decreto recebe URN independente:
  - Lei-mãe: `urn:lex:br:federal:lei:2014-04-23;12965` (Marco Civil)
  - Decreto regulamentador: `urn:lex:br:federal:decreto:2016-05-11;8771` (sem relação sintática)
  - As relações ("regulamenta", "altera", "revoga") são **metadado** — vivem no XML do LexML-BR Parte 3 (campos de ementa e referências internas) e são expostas via OAI-PMH (Parte 4).
  - **Implicação para o RAG:** se quisermos navegar lei↔decretos, precisamos de uma camada de metadados separada (grafo de relações). Não dá pra inferir da URN sozinha. Bom candidato a campo no payload do vector DB.
  - _Fonte: RFC 9676 §5; LexML-BR Parte 3._

- [x] **Súmulas vinculantes do STF — qual a autoridade/tipo na URN?**
  → **Autoridade: `supremo.tribunal.federal`. Tipo: conjectura `sumula.vinculante`.** Súmulas comuns estão indexadas como `urn:lex:br:supremo.tribunal.federal:sumula:YYYY-MM-DD;N` (ex.: `...:sumula:1969-12-03;473`). Súmulas vinculantes — instituto criado pela EC 45/2004 e regulado pela Lei 11.417/2006 — não retornaram exemplo direto no índice na busca, mas a convenção do LexML separa subtipos com ponto (ex.: `lei.complementar`, `medida.provisoria`), então `sumula.vinculante` é o esperado.
  - URN candidata para a Súmula Vinculante nº 11 (uso de algemas, 13/08/2008): `urn:lex:br:supremo.tribunal.federal:sumula.vinculante:2008-08-13;11`.
  - _A verificar abrindo o link candidato no resolver oficial._

---

## 9.5. Jurisprudência (Phase 6 — Tier-4) — esquema URN canônico

> **Decisão de design (2026-05-15):** o RAG passa a indexar jurisprudência como
> 4º _tier_ do corpus. Súmulas STF/STJ + temas de repercussão geral STF entram
> com URNs próprias e _chunks_ atômicos (sem hierarquia LCP-95).

### Tipos URN aceitos

| Tipo URN | Autoridade | Rank | Justificativa |
|---|---|---|---|
| `sumula.vinculante` | `supremo.tribunal.federal` | **2** (= LC) | Efeito vinculante geral / erga omnes (CF art. 103-A, EC 45/2004; Lei 11.417/2006). Atos normativos posteriores não podem contrariar. |
| `tema` | `supremo.tribunal.federal` | **3** (= LO) | Repercussão geral: vincula instâncias inferiores **uma vez fixada a tese**. Tema pendente (sem tese) cai no infralegal — distinção via `nav.status`, não via tipo. |
| `sumula` | `superior.tribunal.justica` ou `supremo.tribunal.federal` | **5** (infralegal) | Súmula simples é orientativa; não tem efeito erga omnes. Vincula apenas internamente ao órgão emissor. |

### Sintaxe canônica

Mesma forma geral `urn:lex:br:<autoridade>:<tipo>:<data>;<id>` da spec RFC 9676 §5:

```
urn:lex:br:supremo.tribunal.federal:sumula.vinculante:2008-08-13;11
urn:lex:br:supremo.tribunal.federal:tema:786
urn:lex:br:superior.tribunal.justica:sumula:1985-04-25;227
```

**Convenções específicas para jurisprudência:**

- **Data**: data de **publicação/aprovação do enunciado** (não da sessão de
  julgamento). Para temas STF onde a data é menos saliente que o número, a
  segmento `<data>;` pode ser omitido — `tema:786` em vez de
  `tema:2018-02-22;786` — porque o número de tema é universalmente único no STF.
- **Partição** (`~<part>`): jurisprudência é atômica. Convenção:
  - `~tese` — texto da tese fixada (para `tema` com tese)
  - `~enunciado` — texto da súmula (para `sumula` / `sumula.vinculante`)
  - `~ementa` — ementa do acórdão paradigma (opcional, para `tema`)
- **`nav` mínimo recomendado**: `tribunal`, `numero`, `status` (`fixada` /
  `pendente` / `cancelada`), `data_aprovacao`, `referencia` (links para tese /
  acórdão paradigma).

### Implicações no `legal_rank` (`rag_leis/legal_rank.py`)

A tabela `LEGAL_RANK_BY_TYPE` foi estendida para refletir os ranks acima.
Súmula vinculante elevada de _infralegal_ → _Lei Complementar_ porque seu efeito
vinculante geral (erga omnes) é estruturalmente equivalente a uma norma de
hierarquia constitucional-derivada — citá-la junto a uma LO/Decreto **não**
deve disparar `hierarchy_warning`. Tema com tese fixada elevado a _LO_ pelo
mesmo princípio (vinculante difusa).

### Por que jurisprudência não usa `ChunkKind` artigo/§/inciso

Súmulas e teses são unidades semânticas únicas, não estruturas hierárquicas.
Forçá-las no esquema LCP-95 (`artigo` → `§` → `inc` → `ali`) seria uma
falsificação. Phase 6.0 introduz `ChunkKind = "jurisprudencia"` como novo
valor literal, ortogonal aos cinco originais. O parser dedicado emite **um
chunk por súmula/tese**, sem `parent_partition`.

### Referências

- CF/88 art. 103-A (incluído pela EC 45/2004) — instituição da súmula vinculante
- Lei 11.417/2006 — regulamenta edição/revisão/cancelamento de súmulas vinculantes
- CPC/2015 art. 927 — rol de precedentes obrigatórios (inclui temas de repercussão geral)
- RISTF (Regimento Interno do STF) — procedimento de afetação e fixação de tese

_Fonte: `study/phase-6-jurisprudencia-plan.md`; convenção LexML observada para subtipos com `.`._

- [x] **Provimentos do CNJ — entram como `federal:resolucao` ou autoridade dedicada?**
  → **Autoridade dedicada `conselho.nacional.justica`.** Resoluções do CNJ estão claramente indexadas: `urn:lex:br:conselho.nacional.justica:resolucao:2007-12-18;48`. Provimentos, no entanto, são emitidos pela **Corregedoria** do CNJ, não pelo Plenário. A convenção LexML para sub-órgãos usa `;` (visto em `supremo.tribunal.federal;plenario` para acórdãos do plenário do STF). Por extensão, provimentos da Corregedoria seriam: `urn:lex:br:conselho.nacional.justica;corregedoria:provimento:YYYY-MM-DD;N`.
  - URN candidata para o Provimento CN-CNJ nº 52/2016 (14/03/2016, reprodução assistida): `urn:lex:br:conselho.nacional.justica;corregedoria:provimento:2016-03-14;52`.
  - _Fonte: catálogo `lexml.gov.br` para resoluções; convenção de sub-autoridade observada em acórdãos do STF._

> **Padrão recorrente nas três conjecturas (ANPD, súmula vinculante, provimento CNJ):** o índice oficial do LexML é incompleto para autoridades regulatórias mais recentes e tipos menos comuns. A spec (RFC 9676 + Parte 2 LexML-BR) é determinística — dá pra gerar a URN do nosso lado com regras. **O resolver é uma cortesia, não a fonte de verdade.** Política do RAG: gerar URNs canônicas; expor link para o resolver; em caso de 404, fallback para o site da autoridade emissora.

---

## 10. Corpus inicial — escopo e composição

### Premissas de escopo (defaults do projeto)

| Decisão | Valor adotado |
|---|---|
| Cobertura temporal | Apenas redação vigente — sem snapshots históricos (`@<data>`) nesta fase. |
| Cobertura da ANPD | Resoluções vinculantes + guias orientativos relevantes. |
| Profundidade penal | Apenas artigos do Código Penal criados/alterados por legislação digital (arts. 154-A, 154-B, 266 §1º, 313-A, 313-B). Não indexar o CP inteiro. |
| Esfera | Federal apenas. Sem legislação estadual ou municipal de proteção de dados. |
| Fontes não-normativas | Não incluir doutrina, artigos acadêmicos ou acórdãos individuais. Súmulas e teses jurisprudenciais ficam para fase futura. |

### Composição por _tier_

A lista por _tier_ vive em arquivos separados — cada um pronto para alimentar o pipeline de ingestão:

| Tier | Arquivo | Conteúdo |
|---|---|---|
| 1 — Núcleo | [`corpus-tier-1-nucleo.md`](corpus-tier-1-nucleo.md) | Leis sem as quais o RAG não cobre o domínio |
| 2 — Complementar | [`corpus-tier-2-complementar.md`](corpus-tier-2-complementar.md) | Adições após o Tier 1 estar funcionando |
| 3 — ANPD | [`corpus-tier-3-anpd.md`](corpus-tier-3-anpd.md) | Resoluções e guias orientativos da ANPD |
| 4 — Condicional | [`corpus-tier-4-condicional.md`](corpus-tier-4-condicional.md) | Entram conforme expansão do escopo |

---

**Fontes principais:**
- [RFC 9676 — LEX: A URN Namespace for Sources of Law](https://datatracker.ietf.org/doc/rfc9676/) (IETF, maio 2025) — §5 sintaxe geral, §7 versionamento
- LexML-BR Norma Técnica Parte 2 (URN LEX)
- [LexML-BR Parte 5 — Serviço de Resolução de URN](https://projeto.lexml.gov.br/documentacao/Parte-5-Servico-de-Resolucao-de-URN.pdf) — comportamento do resolver oficial
- LCP-95/1998 (técnica legislativa brasileira)
- [Projeto LexML — histórico institucional](https://projeto.lexml.gov.br/institucional/historia)
- Catálogo público em `lexml.gov.br/urn/` — utilizado para validar convenções de autoridade e tipo

**Última atualização:** 15 de maio de 2026 (§9.5 — Jurisprudência Tier-4 / Phase 6.0)
