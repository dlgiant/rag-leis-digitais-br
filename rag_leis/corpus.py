from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Document:
    urn: str
    title: str
    planalto_url: str
    # Phase 7.6.2 — per-document scope tags. Each Document declares 5-10
    # concept tags drawn from CONCEPT_VOCABULARY (rag_leis/concept_scope.py).
    # Used by the pre-LLM scope-check gate: query → concept tags → if no
    # indexed doc claims any concept the query touches → refuse before
    # paying for retrieval+LLM. Tuple (not list) because frozen dataclass
    # stays hashable + matches IndexChunk.amended_by pattern.
    document_scope: tuple[str, ...] = ()


TIER_1: tuple[Document, ...] = (
    Document(
        urn="urn:lex:br:federal:constituicao:1988-10-05;1988",
        title="Constituição da República Federativa do Brasil de 1988",
        planalto_url="https://www.planalto.gov.br/ccivil_03/constituicao/constituicao.htm",
        document_scope=(
            "direitos-fundamentais", "habeas-data", "intimidade",
            "direito-imagem", "competencia-uniao", "devido-processo",
            "liberdade-expressao",
        ),
    ),
    Document(
        urn="urn:lex:br:federal:lei:2018-08-14;13709",
        title="LGPD — Lei Geral de Proteção de Dados Pessoais (Lei 13.709/2018)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm",
        document_scope=(
            "dados-pessoais", "consentimento", "DPO", "direitos-titulares",
            "tratamento-dados", "ANPD", "incidente", "vazamento-dados",
            "privacidade",
        ),
    ),
    Document(
        urn="urn:lex:br:federal:lei:2014-04-23;12965",
        title="Marco Civil da Internet (Lei 12.965/2014)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2014/lei/l12965.htm",
        document_scope=(
            "internet", "marco-civil", "neutralidade-rede",
            "guarda-registros", "responsabilidade-provedor", "art-19-mci",
            "liberdade-expressao",
        ),
    ),
    Document(
        urn="urn:lex:br:federal:decreto:2016-05-11;8771",
        title="Decreto 8.771/2016 — regulamenta o Marco Civil da Internet",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2016/decreto/d8771.htm",
        document_scope=(
            "internet", "marco-civil", "neutralidade-rede",
            "guarda-registros", "responsabilidade-provedor",
            "padroes-tecnicos",
        ),
    ),
    Document(
        urn="urn:lex:br:federal:lei:1998-02-19;9609",
        title="Lei do Software (Lei 9.609/1998)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/leis/l9609.htm",
        document_scope=(
            "software", "programa-computador", "direitos-autorais",
            "propriedade-intelectual",
        ),
    ),
    Document(
        urn="urn:lex:br:federal:lei:1998-02-19;9610",
        title="Lei de Direitos Autorais (Lei 9.610/1998)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/leis/l9610.htm",
        document_scope=(
            "direitos-autorais", "obra-intelectual", "autoria",
            "propriedade-intelectual",
        ),
    ),
    Document(
        urn="urn:lex:br:federal:lei:2012-11-30;12737",
        title="Lei Carolina Dieckmann (Lei 12.737/2012)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2012/lei/l12737.htm",
        document_scope=(
            "crimes-ciberneticos", "invasao-dispositivo", "crimes",
        ),
    ),
    Document(
        urn="urn:lex:br:federal:lei:2021-05-27;14155",
        title="Lei 14.155/2021 — Crimes Cibernéticos",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2021/lei/l14155.htm",
        document_scope=(
            "crimes-ciberneticos", "fraude-eletronica",
            "estelionato-digital", "crimes",
        ),
    ),
    Document(
        urn="urn:lex:br:federal:decreto.lei:1940-12-07;2848",
        title="Código Penal (Decreto-Lei 2.848/1940) — texto compilado",
        planalto_url="https://www.planalto.gov.br/ccivil_03/decreto-lei/del2848compilado.htm",
        document_scope=(
            "crimes", "tipicidade", "pena", "dolo-culpa",
            "estelionato-digital",
        ),
    ),
    Document(
        urn="urn:lex:br:federal:lei:2011-11-18;12527",
        title="Lei de Acesso à Informação (Lei 12.527/2011)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2011/lei/l12527.htm",
        document_scope=(
            "acesso-informacao", "transparencia", "governo-aberto",
        ),
    ),
    Document(
        urn="urn:lex:br:federal:lei:2019-07-08;13853",
        title="Lei 13.853/2019 — criação da ANPD",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2019/lei/l13853.htm",
        document_scope=(
            "ANPD", "autoridade-fiscalizacao", "sancao-lgpd",
            "dados-pessoais",
        ),
    ),
    Document(
        urn="urn:lex:br:federal:lei:1990-09-11;8078",
        title="Código de Defesa do Consumidor (Lei 8.078/1990)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/leis/l8078compilado.htm",
        document_scope=(
            "consumidor", "relacao-consumo", "fornecedor",
            "defesa-consumidor",
        ),
    ),
    # Habeas data procedimento — fecha o gold de habeas data que estava
    # incompleto desde Phase 2.5 (CF art.5;LXXII define o remédio; sem
    # esta lei, não tem o procedimento que um advogado responderia).
    Document(
        urn="urn:lex:br:federal:lei:1997-11-12;9507",
        title="Lei 9.507/1997 — disciplina o direito de acesso a informações e o procedimento do habeas data",
        planalto_url="https://www.planalto.gov.br/ccivil_03/leis/l9507.htm",
        document_scope=(
            "habeas-data", "acesso-dados", "retificacao-dados",
            "direitos-titulares",
        ),
    ),
    # Phase 18.1 — Tier-1 expansion. Three docs referenced by existing
    # overlays as "não indexada" until 2026-05-22. All full-document
    # extractions (no scope filter needed — these are short enough to
    # index entirely without retrieval-noise concerns).

    # LC 105/2001 — sigilo bancário. Operative core (arts. 1-6) defines
    # what the financial-secrecy rule is and the judicial-order
    # exception. Referenced by STF Tema 225 (already in Tier-4 via
    # status-aware effective rank) — pre-18.1 the Tema's parent statute
    # was "não indexada".
    Document(
        urn="urn:lex:br:federal:lei.complementar:2001-01-10;105",
        title="LC 105/2001 — dispõe sobre o sigilo das operações de instituições financeiras",
        planalto_url="https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp105.htm",
        document_scope=(
            "sigilo-bancario", "instituicao-financeira", "ordem-judicial",
            "compartilhamento-dados", "receita-federal",
        ),
    ),

    # Lei 12.414/2011 — Cadastro Positivo. Disciplina o banco de dados
    # de adimplemento (histórico de crédito), com regime de consentimento
    # + direitos do cadastrado (arts. 5, 6, 13). Adjacent to LGPD's
    # consent regime — overlays for art-7-LGPD reference this.
    Document(
        urn="urn:lex:br:federal:lei:2011-06-09;12414",
        title="Lei 12.414/2011 — disciplina a formação e consulta a bancos de dados de adimplemento (Cadastro Positivo)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2011/lei/l12414.htm",
        document_scope=(
            "cadastro-positivo", "dados-pessoais", "consentimento",
            "instituicao-financeira", "direitos-titulares",
        ),
    ),

    # Decreto 10.474/2020 — estrutura regimental da ANPD. Regulamenta a
    # Lei 13.853/2019 (que criou a ANPD via emenda à LGPD). Antes da
    # Phase 18.1, overlays referenciavam este Decreto como "estrutura
    # regimental — não indexada"; agora as queries sobre cargos +
    # competência regimental + organograma da ANPD pousam aqui.
    Document(
        urn="urn:lex:br:federal:decreto:2020-08-26;10474",
        title="Decreto 10.474/2020 — Estrutura Regimental e Quadro Demonstrativo dos Cargos em Comissão da ANPD",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2020/decreto/D10474.htm",
        document_scope=(
            "ANPD", "autoridade-fiscalizacao", "estrutura-regimental",
            "competencia-uniao",
        ),
    ),
)


# Tier 2 — complementar. Reviewer-pruned: CDC e EC 115/2022 estavam na lista
# original mas já estão cobertos pelo Tier-1 (CDC indexado + EC 115 integrada
# na CF compilada). Ver study/corpus-tier-2-complementar.md.
TIER_2: tuple[Document, ...] = (
    Document(
        urn="urn:lex:br:federal:lei:2020-09-23;14063",
        title="Lei 14.063/2020 — assinaturas eletrônicas em interações com entes públicos",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2020/lei/l14063.htm",
        document_scope=(
            "assinatura-eletronica", "certificacao-digital",
            "servico-publico-digital",
        ),
    ),
    Document(
        urn="urn:lex:br:federal:lei:2021-03-29;14129",
        title="Lei 14.129/2021 — Lei do Governo Digital",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2021/lei/l14129.htm",
        document_scope=(
            "governo-digital", "servico-publico-digital",
            "transparencia",
        ),
    ),
    Document(
        urn="urn:lex:br:federal:lei:2006-12-19;11419",
        title="Lei 11.419/2006 — informatização do processo judicial",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11419.htm",
        document_scope=(
            "processo-eletronico", "judicial-eletronico",
            "assinatura-eletronica",
        ),
    ),
    # Código Civil — escopo CIRÚRGICO. Indexamos apenas os arts. 11-21
    # (Capítulo II — Dos Direitos da Personalidade) por serem o pilar do
    # direito de imagem / intimidade / honra que entra em queries digitais
    # (Súmula STJ 403, Tema STF 786, etc.). NÃO indexar o CC inteiro
    # (~3.658 chunks) — adicionaria noise e divergiria do escopo digital.
    #
    # IMPORTANT: o parser run em parse_all_tier produz TODOS os chunks do
    # CC e escreve em br_federal_lei_2002-01-10_10406.jsonl. Re-aplicar
    # scripts/filter_cc_personalidade.py logo após — ele SOBRESCREVE o
    # JSONL com a versão filtrada (15 chunks). Se esquecer, load_chunks
    # vai puxar o CC completo e adicionar 3.643 chunks de noise.
    Document(
        urn="urn:lex:br:federal:lei:2002-01-10;10406",
        title="Código Civil (Lei 10.406/2002) — escopo: arts. 11-21 (Direitos da Personalidade)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/leis/2002/l10406compilada.htm",
        document_scope=(
            "direitos-personalidade", "intimidade", "direito-imagem",
            "privacidade",
        ),
    ),
    # Phase 18.1 — ECA escopo CIRÚRGICO. ECA tem ~270 chunks completa;
    # indexamos APENAS os artigos que tocam direito digital + crimes
    # cibernéticos contra crianças/adolescentes:
    #   art. 17-18  — direito ao respeito (inviolabilidade da imagem,
    #                identidade, autonomia, valores) — pilar pra
    #                pedidos de remoção de conteúdo envolvendo menores
    #   art. 78     — exposição de criança em mídia (espelho do CDC
    #                e CF art. 5 V/X aplicado a menores)
    #   art. 240-241-E — crimes contra a dignidade sexual de
    #                criança/adolescente em ambiente digital (gravação,
    #                divulgação, troca, oferta — toda a cadeia
    #                criminalizada pela Lei 11.829/2008 + Lei 13.441/2017)
    #
    # IMPORTANT: mesmo padrão do CC — `parse_all_tier` produz TODOS os
    # chunks do ECA. Re-aplicar `scripts/filter_eca_digital_arts.py`
    # após (Phase 18.1; sobrescreve o JSONL com a versão filtrada).
    # Sem o filtro, ~260 chunks de ECA fora do escopo digital
    # adicionariam noise em retrieval.
    Document(
        urn="urn:lex:br:federal:lei:1990-07-13;8069",
        title="ECA — Estatuto da Criança e do Adolescente (Lei 8.069/1990) — escopo: arts. 17-18, 78, 240-241-E (direito digital + crimes digitais)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/leis/l8069.htm",
        document_scope=(
            "direitos-personalidade", "intimidade", "direito-imagem",
            "crimes-ciberneticos", "menores",
        ),
    ),
)


# Tier 3 — ANPD resoluções. Synthetic URN scheme (Phase 4.3.a, decided
# in study/lexml-urn-spec-resumo.md): `resolucao.cd` qualifies the type
# because ANPD has not all-CD-issued acts. The `planalto_url` field is
# repurposed for ANPD's gov.br canonical path (we keep the same struct
# because the fetch_tier infrastructure is generic; ANPD has no Planalto
# entry).
#
# CAVEAT — Phase 4.3.a only delivers Res. 15/2024 end-to-end (single-PDF
# clean source via lgpd.ms.gov.br mirror). Res. 1/2021, 2/2022, 4/2023 are
# distributed by ANPD as 274-917 page SEI bundles (ofícios + notas técnicas
# + the regulamento). The 20-page Read tool limit makes Claude-Code
# transcription impractical. They are GATED on Phase 4.3.b (real pdfplumber
# parser) before production deploy.
TIER_3: tuple[Document, ...] = (
    Document(
        urn="urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2024-04-24;15",
        title="Resolução CD/ANPD nº 15/2024 — Regulamento de Comunicação de Incidente de Segurança",
        planalto_url="https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd",
        document_scope=(
            "ANPD", "incidente", "vazamento-dados",
            "comunicacao-incidente", "dados-pessoais",
        ),
    ),
    # Res. 4/2023 — Phase 4.3.b real pdfplumber parser. Source PDF is the
    # SEI bundle (917pgs); regulamento extracted from pp.98-108 per
    # ANPD_PARSE_CONFIG. The chunks are produced by AnpdPdfParser and
    # written with source="pdfplumber-v1" audit metadata.
    Document(
        urn="urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2023-02-24;4",
        title="Resolução CD/ANPD nº 4/2023 — Regulamento de Dosimetria e Aplicação de Sanções Administrativas",
        planalto_url="https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd",
        document_scope=(
            "ANPD", "dosimetria", "sancao-lgpd",
            "autoridade-fiscalizacao",
        ),
    ),
    # ----------------------------------------------------------------------
    # The 2 below STILL gated. Res. 1/2021 is in a 807-page bundle (could
    # be done with the pdfplumber parser but page_range not yet curated).
    # Res. 2/2022 part1 has (cid:XXX) font-encoding issue — would need
    # OCR fallback (pytesseract). Both deferred to follow-on work.
    # ----------------------------------------------------------------------
    # Document(
    #     urn="urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2021-10-28;1",
    #     title="Resolução CD/ANPD nº 1/2021 — Regulamento do Processo de Fiscalização e Sancionador",
    #     planalto_url="https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd",
    # ),
    # Document(
    #     urn="urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2022-01-27;2",
    #     title="Resolução CD/ANPD nº 2/2022 — Aplicação da LGPD a agentes de tratamento de pequeno porte",
    #     planalto_url="https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd",
    # ),
)


# Tier 4 — jurisprudência (Phase 6.1). Súmulas STJ + temas de repercussão geral
# STF. Cada Document aqui é um enunciado/tese atômico — sem hierarquia LCP-95.
# `planalto_url` repurposed para portal.stf.jus.br / scon.stj.jus.br (mesmo
# precedent do Tier-3 ANPD: o struct é genérico, o caminho é canônico do tribunal).
#
# Ingestion: manual (Phase 6.1) — chunks escritos à mão pelo Claude Code com
# texto verbatim de fontes públicas (STJ súmulas) ou stubs marcados como
# `status: "pendente_revisao_juridica"` para itens cuja tese verbatim depende
# de revisão D7 (lawyer-review-checklist.md item 5).
#
# Real scrapers contra portal.stf.jus.br + scon.stj.jus.br ficam para Phase 6.3
# (gated). Hierarchy warning para distinguir tese-fixada vs pendente é Phase 6.5.
TIER_4: tuple[Document, ...] = (
    # STJ Súmulas — Segunda Seção / Corte Especial. Rank 5 (orientativa).
    Document(
        urn="urn:lex:br:superior.tribunal.justica:sumula:1999-09-08;227",
        title="STJ Súmula 227 — Pessoa jurídica e dano moral",
        planalto_url="https://scon.stj.jus.br/SCON/sumanot/toc.jsp?livre=(sumula%20adj1%20%27227%27).sub.",
        document_scope=(
            "dano-moral", "pessoa-juridica", "responsabilidade-civil",
        ),
    ),
    Document(
        urn="urn:lex:br:superior.tribunal.justica:sumula:2009-10-28;403",
        title="STJ Súmula 403 — Publicação não autorizada de imagem com fins econômicos",
        planalto_url="https://scon.stj.jus.br/SCON/sumanot/toc.jsp?livre=(sumula%20adj1%20%27403%27).sub.",
        document_scope=(
            "direito-imagem", "publicacao-nao-autorizada", "dano-moral",
            "direitos-personalidade",
        ),
    ),
    Document(
        urn="urn:lex:br:superior.tribunal.justica:sumula:2012-06-27;479",
        title="STJ Súmula 479 — Responsabilidade objetiva das instituições financeiras por fraude de terceiros",
        planalto_url="https://scon.stj.jus.br/SCON/sumanot/toc.jsp?livre=(sumula%20adj1%20%27479%27).sub.",
        document_scope=(
            "instituicao-financeira", "responsabilidade-objetiva",
            "fraude-terceiros",
        ),
    ),
    # STF Temas de Repercussão Geral. Rank 3 quando tese fixada.
    # Tema 786 — tese fixada 11/02/2021 (ARE 833.248, Caso Aída Curi).
    Document(
        urn="urn:lex:br:supremo.tribunal.federal:tema:786",
        title="STF Tema 786 — Direito ao esquecimento (incompatibilidade com a Constituição)",
        planalto_url="https://portal.stf.jus.br/jurisprudenciaRepercussao/verAndamentoProcesso.asp?incidente=4623869&numeroProcesso=833248",
        document_scope=(
            "direito-esquecimento", "intimidade", "liberdade-expressao",
        ),
    ),
    # Tema 987 — RE 1.037.396 + RE 1.057.258. Julgamento concluído em jun/2024
    # (declaração de inconstitucionalidade parcial do art. 19 MCI). Stub aqui:
    # tese verbatim depende de revisão D7 antes de produção.
    Document(
        urn="urn:lex:br:supremo.tribunal.federal:tema:987",
        title="STF Tema 987 — Constitucionalidade do art. 19 do Marco Civil da Internet",
        planalto_url="https://portal.stf.jus.br/jurisprudenciaRepercussao/verAndamentoProcesso.asp?incidente=5160549&numeroProcesso=1037396",
        document_scope=(
            "art-19-mci", "responsabilidade-provedor", "marco-civil",
        ),
    ),
    # Tema 533 — RE 601.314. Sigilo bancário e Receita Federal sem ordem judicial.
    # Stub: tese verbatim depende de revisão D7.
    Document(
        urn="urn:lex:br:supremo.tribunal.federal:tema:533",
        title="STF Tema 533 — Compartilhamento de dados bancários com a Receita Federal",
        planalto_url="https://portal.stf.jus.br/jurisprudenciaRepercussao/verAndamentoProcesso.asp?incidente=2641697&numeroProcesso=601314",
        document_scope=(
            "sigilo-bancario", "receita-federal", "compartilhamento-dados",
        ),
    ),
    # Tema 815 — RE 1.058.244. Bloqueio judicial de aplicações por
    # descumprimento. Stub: tese verbatim depende de revisão D7.
    Document(
        urn="urn:lex:br:supremo.tribunal.federal:tema:815",
        title="STF Tema 815 — Bloqueio judicial de aplicações de internet por descumprimento de ordem",
        planalto_url="https://portal.stf.jus.br/jurisprudenciaRepercussao/verTemasComRepercussaoGeral.asp",
        document_scope=(
            "bloqueio-aplicacao", "ordem-judicial", "marco-civil",
        ),
    ),
)


# Phase 7.6.2 — registry lookup by document URN. Builds the union of all
# four tiers into a single dict for O(1) doc-URN → Document resolution.
# Used by rag.py's concept-scope gate to look up document_scope from a
# retrieved chunk's URN (via chunk_urn.split("~", 1)[0]).
CORPUS_BY_URN: dict[str, Document] = {
    d.urn: d for d in (*TIER_1, *TIER_2, *TIER_3, *TIER_4)
}
