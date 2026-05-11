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

## 9. Questões em aberto para investigar

Anote no notebook conforme for descobrindo:

- [ ] Como o LexML lida com _"redação dada pela Lei X"_? Mesma URN com componente de versão (`@`), ou URN distinta?
- [ ] Artigos revogados continuam endereçáveis por URN? _(Spoiler: sim — a URN identifica a obra; revogação é metadado.)_
- [ ] A **ANPD** tem código de autoridade reconhecido na URN, ou suas resoluções resolvem sob `federal:resolucao`?
- [ ] Como decretos regulamentadores (ex.: Decreto 8.771/16 do Marco Civil) se relacionam à URN da lei-mãe? Existe componente de relação?
- [ ] Súmulas vinculantes do STF — qual a autoridade/tipo na URN?
- [ ] Provimentos do CNJ — entram como `federal:resolucao` ou autoridade dedicada?


---

**Fontes principais:**
- RFC 9676 — LEX: A URN Namespace for Sources of Law (IETF, maio 2025)
- LexML-BR Norma Técnica Parte 2 (URN LEX)
- LCP-95/1998 (técnica legislativa brasileira)
- Projeto LexML — histórico institucional (projeto.lexml.gov.br)

**Última atualização:** 11 de maio de 2026
