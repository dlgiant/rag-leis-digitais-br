from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Document:
    urn: str
    title: str
    planalto_url: str


TIER_1: tuple[Document, ...] = (
    Document(
        urn="urn:lex:br:federal:constituicao:1988-10-05;1988",
        title="Constituição da República Federativa do Brasil de 1988",
        planalto_url="https://www.planalto.gov.br/ccivil_03/constituicao/constituicao.htm",
    ),
    Document(
        urn="urn:lex:br:federal:lei:2018-08-14;13709",
        title="LGPD — Lei Geral de Proteção de Dados Pessoais (Lei 13.709/2018)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm",
    ),
    Document(
        urn="urn:lex:br:federal:lei:2014-04-23;12965",
        title="Marco Civil da Internet (Lei 12.965/2014)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2014/lei/l12965.htm",
    ),
    Document(
        urn="urn:lex:br:federal:decreto:2016-05-11;8771",
        title="Decreto 8.771/2016 — regulamenta o Marco Civil da Internet",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2016/decreto/d8771.htm",
    ),
    Document(
        urn="urn:lex:br:federal:lei:1998-02-19;9609",
        title="Lei do Software (Lei 9.609/1998)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/leis/l9609.htm",
    ),
    Document(
        urn="urn:lex:br:federal:lei:1998-02-19;9610",
        title="Lei de Direitos Autorais (Lei 9.610/1998)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/leis/l9610.htm",
    ),
    Document(
        urn="urn:lex:br:federal:lei:2012-11-30;12737",
        title="Lei Carolina Dieckmann (Lei 12.737/2012)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2012/lei/l12737.htm",
    ),
    Document(
        urn="urn:lex:br:federal:lei:2021-05-27;14155",
        title="Lei 14.155/2021 — Crimes Cibernéticos",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2021/lei/l14155.htm",
    ),
    Document(
        urn="urn:lex:br:federal:decreto.lei:1940-12-07;2848",
        title="Código Penal (Decreto-Lei 2.848/1940) — texto compilado",
        planalto_url="https://www.planalto.gov.br/ccivil_03/decreto-lei/del2848compilado.htm",
    ),
    Document(
        urn="urn:lex:br:federal:lei:2011-11-18;12527",
        title="Lei de Acesso à Informação (Lei 12.527/2011)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2011/lei/l12527.htm",
    ),
    Document(
        urn="urn:lex:br:federal:lei:2019-07-08;13853",
        title="Lei 13.853/2019 — criação da ANPD",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2019/lei/l13853.htm",
    ),
    Document(
        urn="urn:lex:br:federal:lei:1990-09-11;8078",
        title="Código de Defesa do Consumidor (Lei 8.078/1990)",
        planalto_url="https://www.planalto.gov.br/ccivil_03/leis/l8078compilado.htm",
    ),
    # Habeas data procedimento — fecha o gold de habeas data que estava
    # incompleto desde Phase 2.5 (CF art.5;LXXII define o remédio; sem
    # esta lei, não tem o procedimento que um advogado responderia).
    Document(
        urn="urn:lex:br:federal:lei:1997-11-12;9507",
        title="Lei 9.507/1997 — disciplina o direito de acesso a informações e o procedimento do habeas data",
        planalto_url="https://www.planalto.gov.br/ccivil_03/leis/l9507.htm",
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
    ),
    Document(
        urn="urn:lex:br:federal:lei:2021-03-29;14129",
        title="Lei 14.129/2021 — Lei do Governo Digital",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2021/lei/l14129.htm",
    ),
    Document(
        urn="urn:lex:br:federal:lei:2006-12-19;11419",
        title="Lei 11.419/2006 — informatização do processo judicial",
        planalto_url="https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11419.htm",
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
    ),
    # Res. 4/2023 — Phase 4.3.b real pdfplumber parser. Source PDF is the
    # SEI bundle (917pgs); regulamento extracted from pp.98-108 per
    # ANPD_PARSE_CONFIG. The chunks are produced by AnpdPdfParser and
    # written with source="pdfplumber-v1" audit metadata.
    Document(
        urn="urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2023-02-24;4",
        title="Resolução CD/ANPD nº 4/2023 — Regulamento de Dosimetria e Aplicação de Sanções Administrativas",
        planalto_url="https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd",
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
    ),
    Document(
        urn="urn:lex:br:superior.tribunal.justica:sumula:2009-10-28;403",
        title="STJ Súmula 403 — Publicação não autorizada de imagem com fins econômicos",
        planalto_url="https://scon.stj.jus.br/SCON/sumanot/toc.jsp?livre=(sumula%20adj1%20%27403%27).sub.",
    ),
    Document(
        urn="urn:lex:br:superior.tribunal.justica:sumula:2012-06-27;479",
        title="STJ Súmula 479 — Responsabilidade objetiva das instituições financeiras por fraude de terceiros",
        planalto_url="https://scon.stj.jus.br/SCON/sumanot/toc.jsp?livre=(sumula%20adj1%20%27479%27).sub.",
    ),
    # STF Temas de Repercussão Geral. Rank 3 quando tese fixada.
    # Tema 786 — tese fixada 11/02/2021 (ARE 833.248, Caso Aída Curi).
    Document(
        urn="urn:lex:br:supremo.tribunal.federal:tema:786",
        title="STF Tema 786 — Direito ao esquecimento (incompatibilidade com a Constituição)",
        planalto_url="https://portal.stf.jus.br/jurisprudenciaRepercussao/verAndamentoProcesso.asp?incidente=4623869&numeroProcesso=833248",
    ),
    # Tema 987 — RE 1.037.396 + RE 1.057.258. Julgamento concluído em jun/2024
    # (declaração de inconstitucionalidade parcial do art. 19 MCI). Stub aqui:
    # tese verbatim depende de revisão D7 antes de produção.
    Document(
        urn="urn:lex:br:supremo.tribunal.federal:tema:987",
        title="STF Tema 987 — Constitucionalidade do art. 19 do Marco Civil da Internet",
        planalto_url="https://portal.stf.jus.br/jurisprudenciaRepercussao/verAndamentoProcesso.asp?incidente=5160549&numeroProcesso=1037396",
    ),
    # Tema 533 — RE 601.314. Sigilo bancário e Receita Federal sem ordem judicial.
    # Stub: tese verbatim depende de revisão D7.
    Document(
        urn="urn:lex:br:supremo.tribunal.federal:tema:533",
        title="STF Tema 533 — Compartilhamento de dados bancários com a Receita Federal",
        planalto_url="https://portal.stf.jus.br/jurisprudenciaRepercussao/verAndamentoProcesso.asp?incidente=2641697&numeroProcesso=601314",
    ),
    # Tema 815 — RE 1.058.244. Bloqueio judicial de aplicações por
    # descumprimento. Stub: tese verbatim depende de revisão D7.
    Document(
        urn="urn:lex:br:supremo.tribunal.federal:tema:815",
        title="STF Tema 815 — Bloqueio judicial de aplicações de internet por descumprimento de ordem",
        planalto_url="https://portal.stf.jus.br/jurisprudenciaRepercussao/verTemasComRepercussaoGeral.asp",
    ),
)
