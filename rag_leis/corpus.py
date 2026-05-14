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
