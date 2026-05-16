"""Tests for the per-query router (title-prefix vs baseline)."""

from __future__ import annotations

import pytest

from rag_leis.query_router import mentions_law_name


@pytest.mark.parametrize(
    "query",
    [
        "o que diz o art. 13 do Marco Civil?",
        "o que diz o art. 13 do Marco Civil da Internet?",
        "qual a definição de dado pessoal na LGPD?",
        "Lei Geral de Proteção de Dados pessoais é federal ou estadual?",
        "Código Penal art. 154-A",
        "código penal e crimes cibernéticos",
        "Código Civil art. 20 fala de imagem",
        "código de defesa do consumidor protege consumidor",
        "Lei do Software brasileira",
        "Lei de Direitos Autorais e citação acadêmica",
        "Lei de Acesso à Informação",
        "LAI permite pedido de informação",
        "ANPD pode aplicar multa?",
        "Resolução CD/ANPD nº 4/2023",
        "Constituição Federal art. 5 inciso X",
        "constituição garante intimidade",
        "Súmula 227 do STJ",
        "Súmula Vinculante nº 11",
        "Tema 786 do STF",
        "STF Tema 987",
        "Lei 13709",
        "Lei nº 13.709/2018",
        "Lei 14.155/21",
        "Decreto 8.771/2016",
        "Decreto-Lei 2.848/1940",
        "habeas data",
        "como funciona habeas corpus",
    ],
)
def test_law_name_detected(query):
    assert mentions_law_name(query), f"should detect law name in: {query!r}"


@pytest.mark.parametrize(
    "query",
    [
        "preciso pedir autorização pra mandar e-mail marketing?",
        "fui invadido no celular sem permissão, isso é crime?",
        "minha empresa precisa nomear alguém responsável pelos dados?",
        "se vazaram meus dados, alguém me avisa?",
        "policial pode pedir meus dados pra investigar crime?",
        "clonaram meu cartão pela internet, qual artigo se aplica?",
        "preciso de autorização para usar a foto de uma pessoa em uma propaganda?",
        "tenho um e-commerce pequeno, preciso seguir todas as regras?",
        "como faço pra pedir uma informação pra uma prefeitura?",
        "transferiram dinheiro da minha conta sem permissão, qual o crime?",
        "pena maior pra estelionato cometido pela internet?",
        # Edge cases that look risky but should be False:
        "comportamento abusivo nas redes",
        "vida privada é protegida pela lei?",
        "responsabilidade do provedor de aplicações por conteúdo de usuários",
    ],
)
def test_no_law_name(query):
    assert not mentions_law_name(query), f"should NOT detect law in: {query!r}"
