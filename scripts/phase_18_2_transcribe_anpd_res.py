"""Phase 18.2 — manual transcription of Res. CD/ANPD 1/2021 + 2/2022 arts 1-15.

Both resolutions are referenced as "não indexada" by existing overlays
(e.g., the LGPD art. 55-A `eficacia_limitada` entry cites Res. 2/2022).
The ANPD publishes them as HTML on gov.br but historically the project
parsed only Res. 4/2023 + Res. 15/2024 via pdfplumber. This script
fills the gap with verbatim transcription from the gov.br HTML source.

WHY MANUAL TRANSCRIPTION (not parser):
  * Res. 1/2021 has 71 articles; arts 1-15 are the operative core
    (Capítulo I — Disposições Gerais + Capítulo II — Fiscalização +
    início do Capítulo III — Processo Administrativo Sancionador).
    Transcribing all 71 would multiply chunks without proportional
    legal-coverage gain. The roadmap (study/phase-16-19-roadmap.md
    Phase 18.2) explicitly says "operative articles ... arts. 1-15".
  * Res. 2/2022 has ~16 operative articles in the regulamento + an
    appendix. Arts 1-15 cover the entire substantive content.
  * The gov.br HTML is structured but inconsistently — running the
    project's HTML parser produces noisy chunks (extra TOC entries,
    "publicado em" boilerplate, footnote-like elements). Manual
    transcription avoids the cleanup cost.

SOURCE ATTRIBUTION:
  * fetched 2026-05-22 via WebFetch from:
    - https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/
      atos-normativos/regulamentacoes_anpd/resolucao-cd-anpd-no1-2021
    - https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/
      atos-normativos/regulamentacoes_anpd/resolucao-cd-anpd-no-2-de-
      27-de-janeiro-de-2022
  * chunk `source` field: "manual-transcription-anpd-html-v1"
  * chunk `ingestion_method`: "manual_html_transcription"
  * chunk `ingestion_provenance`: "Phase 18.2; gov.br official ANPD
    HTML; fetched 2026-05-22"

RUN:
  uv run python scripts/phase_18_2_transcribe_anpd_res.py

OUTPUT:
  data/chunks/tier-3/anpd_res_1_2021.jsonl
  data/chunks/tier-3/anpd_res_2_2022.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "data" / "chunks" / "tier-3"
PROVENANCE = "Phase 18.2; gov.br official ANPD HTML; fetched 2026-05-22"
SOURCE_TAG = "manual-transcription-anpd-html-v1"
INGESTION_METHOD = "manual_html_transcription"


# ---------------------------------------------------------------------------
# Resolução CD/ANPD nº 1/2021 — arts 1-15
# Regulamento do Processo de Fiscalização e do Processo Administrativo
# Sancionador no âmbito da ANPD. Publicada 2021-10-29 (DOU);
# enactment date 2021-10-28.
# ---------------------------------------------------------------------------

RES_1_2021: dict[str, Any] = {
    "urn": "urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2021-10-28;1",
    "title": "Resolução CD/ANPD nº 1/2021 — Regulamento do Processo de Fiscalização e do Processo Administrativo Sancionador",
    "nav": {"resolucao": "Res. CD/ANPD 1/2021"},
    "articles": [
        {
            "n": 1,
            "caput": "Este Regulamento tem por objetivo estabelecer os procedimentos inerentes ao processo de fiscalização e as regras a serem observadas no âmbito do processo administrativo sancionador pela Autoridade Nacional de Proteção de Dados (ANPD).",
            "paragraphs": [
                {"n": 1, "text": "As disposições deste regulamento aplicam-se aos titulares de dados, aos agentes de tratamento, pessoas naturais ou jurídicas, de direito público ou privado e demais interessados no tratamento de dados pessoais, nos termos do art. 13."},
                {"n": 2, "text": "As disposições da Lei nº 9.784, de 29 de janeiro de 1999, aplicam-se subsidiariamente a este Regulamento."},
            ],
        },
        {
            "n": 2,
            "caput": "A fiscalização compreende as atividades de monitoramento, orientação e atuação preventiva, conforme os procedimentos previstos neste Regulamento.",
            "paragraphs": [
                {"n": 1, "text": "A aplicação de sanção ocorrerá em conformidade com a regulamentação específica, por meio de processo administrativo sancionador, definido neste Regulamento."},
                {"n": 2, "text": "A atividade de fiscalização da ANPD terá por finalidade orientar, prevenir e reprimir as infrações à Lei nº 13.709, de 14 de agosto de 2018 (Lei Geral de Proteção de Dados Pessoais - LGPD)."},
            ],
        },
        {
            "n": 3,
            "caput": "A ANPD atuará para a proteção dos direitos dos titulares de dados, para promover a implementação da legislação de proteção de dados pessoais, e para zelar pelo seu cumprimento.",
        },
        {
            "n": 4,
            "caput": "As seguintes definições são adotadas neste Regulamento:",
            "incisos": [
                {"n": 1, "text": "agentes regulados: agentes de tratamento e demais integrantes ou interessados no tratamento de dados pessoais"},
                {"n": 2, "text": "autuado: agente regulado que, uma vez identificados indícios suficientes de conduta infrativa, tem instaurado processo administrativo sancionador contra si, por meio de auto de infração"},
                {"n": 3, "text": "denúncia: comunicação feita à ANPD por qualquer pessoa, natural ou jurídica, de suposta infração cometida contra a legislação de proteção de dados pessoais do País, que não seja uma petição de titular"},
                {"n": 4, "text": "obstrução à atividade de fiscalização: ato, comissivo ou omissivo, direto ou indireto, da fiscalização ou de seus pressupostos, que impeça, dificulte ou embarace a atividade de fiscalização exercida pela ANPD"},
                {"n": 5, "text": "petição de titular: comunicação feita à ANPD pelo titular de dados pessoais de uma solicitação apresentada ao controlador e não solucionada no prazo estabelecido em regulamentação"},
                {"n": 6, "text": "requerimento: conjunto de tipos de comunicação, compreendendo a petição de titular e a denúncia."},
            ],
        },
        {
            "n": 5,
            "caput": "Os agentes regulados submetem-se à fiscalização da ANPD e têm os seguintes deveres, dentre outros:",
            "incisos": [
                {"n": 1, "text": "fornecer cópia de documentos, físicos ou digitais, dados e informações relevantes para a avaliação das atividades de tratamento de dados pessoais, no prazo, local, formato e demais condições estabelecidas pela ANPD"},
                {"n": 2, "text": "permitir o acesso às instalações, equipamentos, aplicativos, facilidades, sistemas, ferramentas e recursos tecnológicos, documentos, dados e informações de natureza técnica, operacional e outras relevantes"},
                {"n": 3, "text": "possibilizar que a ANPD tenha conhecimento dos sistemas de informação utilizados para tratamento de dados e informações"},
                {"n": 4, "text": "submeter-se a auditorias realizadas ou determinadas pela ANPD"},
                {"n": 5, "text": "manter os documentos físicos ou digitais, os dados e as informações durante os prazos estabelecidos na legislação e em regulamentação específica"},
                {"n": 6, "text": "disponibilizar, sempre que requisitado, representante apto a oferecer suporte à atuação da ANPD"},
            ],
            "paragraphs": [
                {"n": 1, "text": "Os documentos, dados e as informações requisitados, recebidos, obtidos e acessados pela ANPD nos termos deste Regulamento são aqueles necessários ao exercício efetivo das suas atribuições"},
                {"n": 2, "text": "Cabe ao agente regulado solicitar à ANPD o sigilo de informações relativas à sua atividade empresarial"},
                {"n": 3, "text": "Os documentos apresentados sob a forma digitalizada deverão cumprir os requisitos estabelecidos pelo Decreto nº 10.278, de 18 de março de 2020."},
                {"n": 4, "text": "O agente regulado, por intermédio de representante indicado, poderá acompanhar a auditoria da ANPD"},
            ],
        },
        {
            "n": 6,
            "caput": "O não cumprimento dos deveres estabelecidos no art. 5º poderá caracterizar obstrução à atividade de fiscalização, sujeitando o infrator a medidas repressivas",
        },
        {
            "n": 7,
            "caput": "As disposições processuais deste Capítulo aplicam-se às interações realizadas entre as unidades da ANPD e os agentes regulados nas hipóteses deste Regulamento.",
        },
        {
            "n": 8,
            "caput": "Os prazos definidos neste regulamento começam a correr a partir da ciência oficial e são contados em dias úteis",
            "paragraphs": [
                {"n": 1, "text": "O prazo para a prática de ato será prorrogado para o primeiro dia útil seguinte, caso no dia de seu vencimento não haja expediente na sede da ANPD"},
                {
                    "n": 2,
                    "text": "O prazo também será prorrogado, na forma do § 1º, em caso de comprovada indisponibilidade do sistema eletrônico de peticionamento",
                    "incisos": [
                        {"n": 1, "text": "por período superior a três horas, ininterruptas ou não, se ocorrida entre 6h00 e 23h00"},
                        {"n": 2, "text": "caso a indisponibilidade ocorra entre 23h00 e 24h00"},
                    ],
                },
            ],
        },
        {
            "n": 9,
            "caput": "A expedição dos atos administrativos ocorrerá por determinação motivada pela autoridade competente.",
        },
        {
            "n": 10,
            "caput": "Os atos administrativos serão comunicados por intermédio de intimação, nos termos do art. 12 deste Regulamento, que deverá conter:",
            "incisos": [
                {"n": 1, "text": "a identificação do intimado"},
                {"n": 2, "text": "a finalidade da intimação e a informação de continuidade do processo independentemente do seu comparecimento"},
                {"n": 3, "text": "a data, a hora e o local, ou o prazo para tomada da providência, quando houver"},
                {"n": 4, "text": "a informação se o intimado deve comparecer pessoalmente, fazer-se representar, manifestar-se ou apresentar defesa ou recurso no processo"},
                {"n": 5, "text": "a indicação dos fatos e fundamentos legais pertinentes."},
            ],
        },
        {
            "n": 11,
            "caput": "Os atos administrativos serão realizados, preferencialmente, por meio eletrônico, em regra, adotado pela ANPD, podendo ocorrer, inclusive, mediante videoconferência ou outro recurso tecnológico de transmissão de sons e imagens em tempo real.",
            "parag_unico": "Excepcionalmente, a ANPD poderá expedir comunicação por suporte físico, ou por qualquer outro recurso que assegure a certeza da ciência do interessado.",
        },
        {
            "n": 12,
            "caput": "Considera-se efetuada a ciência oficial com a intimação:",
            "incisos": [
                {"n": 1, "text": "por meio eletrônico, na data em que o usuário realizar a consulta ao documento correspondente ou, caso não realizada a consulta, dez dias úteis após o envio da intimação"},
                {"n": 2, "text": "por via postal, na data de recebimento do Aviso de Recebimento (AR) ou documento equivalente"},
                {"n": 3, "text": "pessoalmente, na data da ciência do intimado, seu representante, preposto ou, no caso de recusa de ciência"},
                {"n": 4, "text": "quando a parte comparecer, pessoalmente ou devidamente representada, para tomar ciência do processo"},
                {"n": 5, "text": "por edital, na data de sua publicação"},
                {"n": 6, "text": "por outro meio, que assegure a certeza da ciência do interessado"},
                {"n": 7, "text": "por mecanismos de cooperação internacional, na forma estabelecida no Decreto nº 9.734, de 20 de março de 2019"},
            ],
            "paragraphs": [
                {"n": 1, "text": "Frustrada a tentativa por via postal ou quando desconhecido ou incerto o endereço do intimado, a intimação será feita por edital publicado no Diário Oficial da União."},
                {"n": 2, "text": "O interessado deve informar, na primeira oportunidade em que se manifeste no processo, endereço eletrônico válido em que receberá as comunicações."},
            ],
        },
        {
            "n": 13,
            "caput": "São interessados nos processos administrativos de que trata este regulamento, observados o segredo comercial e o industrial:",
            "incisos": [
                {"n": 1, "text": "pessoas naturais ou jurídicas, que o iniciem como titulares de direitos, com interesses individuais ou no exercício do direito de representação"},
                {"n": 2, "text": "aqueles que, sem terem iniciado o processo, têm direitos ou interesses que possam ser afetados pela decisão a ser adotada"},
                {"n": 3, "text": "as organizações e associações representativas, no tocante a direitos e interesses coletivos"},
                {"n": 4, "text": "as pessoas ou as associações legalmente constituídas quanto a direitos ou interesses difusos, incluindo as instituições acadêmicas."},
            ],
        },
        {
            "n": 14,
            "caput": "Será conferida prioridade na tramitação dos processos conforme hipóteses previstas em lei",
            "paragraphs": [
                {"n": 1, "text": "A autoridade competente para apreciar o pedido de que trata o caput determinará as providências a serem cumpridas na tramitação do processo."},
                {"n": 2, "text": "Deferida a prioridade, os autos receberão identificação própria que evidencie o regime de tramitação prioritária."},
            ],
        },
        {
            "n": 15,
            "caput": "A ANPD adotará atividades de monitoramento, de orientação e de prevenção no processo de fiscalização e poderá iniciar a atividade repressiva.",
            "paragraphs": [
                {"n": 1, "text": "A atividade de monitoramento destina-se ao levantamento de informações e dados relevantes para subsidiar a tomada de decisões pela ANPD"},
                {"n": 2, "text": "A atividade de orientação caracteriza-se pela atuação baseada na economicidade e na utilização de métodos e ferramentas"},
                {"n": 3, "text": "A atividade preventiva consiste em uma atuação baseada, preferencialmente, na construção conjunta e dialogada de soluções"},
                {"n": 4, "text": "A atividade repressiva caracteriza-se pela atuação coercitiva da ANPD, voltada à interrupção de situações de dano ou risco"},
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# Resolução CD/ANPD nº 2/2022 — arts 1-15
# Regulamento de aplicação da LGPD para agentes de tratamento de pequeno
# porte. Publicada 2022-01-27.
# ---------------------------------------------------------------------------

RES_2_2022: dict[str, Any] = {
    "urn": "urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2022-01-27;2",
    "title": "Resolução CD/ANPD nº 2/2022 — Regulamento de aplicação da LGPD para agentes de tratamento de pequeno porte",
    "nav": {"resolucao": "Res. CD/ANPD 2/2022"},
    "articles": [
        {
            "n": 1,
            "caput": "Este regulamento tem por objetivo regulamentar a aplicação da Lei nº 13.709, de 14 de agosto de 2018, Lei Geral de Proteção de Dados Pessoais (LGPD), para agentes de tratamento de pequeno porte, com base nas competências previstas no art. 55-J, inciso XVIII, da referida Lei.",
            "parag_unico": "Este regulamento não se aplica ao tratamento de dados pessoais realizado por pessoa natural para fins exclusivamente particulares e não econômicos, bem como nas demais hipóteses previstas no art. 4º da LGPD.",
        },
        {
            "n": 2,
            "caput": "Para efeitos deste regulamento são adotadas as seguintes definições:",
            "incisos": [
                {"n": 1, "text": "agentes de tratamento de pequeno porte: microempresas, empresas de pequeno porte, startups, pessoas jurídicas de direito privado, inclusive sem fins lucrativos, nos termos da legislação vigente, bem como pessoas naturais e entes privados despersonalizados que realizam tratamento de dados pessoais, assumindo obrigações típicas de controlador ou de operador"},
                {"n": 2, "text": "microempresas e empresas de pequeno porte: sociedade empresária, sociedade simples, sociedade limitada unipessoal, nos termos do art. 41 da Lei nº 14.195, de 26 de agosto de 2021, e o empresário a que se refere o art. 966 da Lei nº 10.406, de 10 de janeiro de 2002 (Código Civil), incluído o microempreendedor individual, devidamente registrados no Registro de Empresas Mercantis ou no Registro Civil de Pessoas Jurídicas, que se enquadre nos termos do art. 3º e 18-A, §1º da Lei Complementar nº 123, de 14 de dezembro de 2006"},
                {"n": 3, "text": "startups: organizações empresariais ou societárias, nascentes ou em operação recente, cuja atuação caracteriza-se pela inovação aplicada a modelo de negócios ou a produtos ou serviços ofertados, que atendam aos critérios previstos no Capítulo II da Lei Complementar nº 182, de 1º de junho de 2021"},
                {"n": 4, "text": "zonas acessíveis ao público: espaços abertos ao público, como praças, centros comerciais, vias públicas, estações de ônibus, de metrô e de trem, aeroportos, portos, bibliotecas públicas, dentre outros"},
            ],
        },
        {
            "n": 3,
            "caput": "Não poderão se beneficiar do tratamento jurídico diferenciado previsto neste Regulamento os agentes de tratamento de pequeno porte que:",
            "incisos": [
                {"n": 1, "text": "realizem tratamento de alto risco para os titulares, ressalvada a hipótese prevista no art. 8º"},
                {"n": 2, "text": "aufiram receita bruta superior ao limite estabelecido no art. 3º, II, da Lei Complementar nº 123, de 2006 ou, no caso de startups, no art. 4º, § 1º, I, da Lei Complementar nº 182, de 2021"},
                {"n": 3, "text": "pertençam a grupo econômico de fato ou de direito, cuja receita global ultrapasse os limites referidos no inciso II, conforme o caso"},
            ],
        },
        {
            "n": 4,
            "caput": "Para fins deste regulamento, e sem prejuízo do disposto no art. 16, será considerado de alto risco o tratamento de dados pessoais que atender cumulativamente a pelo menos um critério geral e um critério específico, dentre os a seguir indicados:",
            "incisos": [
                {
                    "n": 1,
                    "text": "critérios gerais:",
                    "alineas": [
                        {"letter": "a", "text": "tratamento de dados pessoais em larga escala"},
                        {"letter": "b", "text": "tratamento de dados pessoais que possa afetar significativamente interesses e direitos fundamentais dos titulares"},
                    ],
                },
                {
                    "n": 2,
                    "text": "critérios específicos:",
                    "alineas": [
                        {"letter": "a", "text": "uso de tecnologias emergentes ou inovadoras"},
                        {"letter": "b", "text": "vigilância ou controle de zonas acessíveis ao público"},
                        {"letter": "c", "text": "decisões tomadas unicamente com base em tratamento automatizado de dados pessoais, inclusive aquelas destinadas a definir o perfil pessoal, profissional, de saúde, de consumo e de crédito ou os aspectos da personalidade do titular"},
                        {"letter": "d", "text": "utilização de dados pessoais sensíveis ou de dados pessoais de crianças, de adolescentes e de idosos"},
                    ],
                },
            ],
            "paragraphs": [
                {"n": 1, "text": "O tratamento de dados pessoais em larga escala será caracterizado quando abranger número significativo de titulares, considerando-se, ainda, o volume de dados envolvidos, bem como a duração, a frequência e a extensão geográfica do tratamento realizado"},
                {"n": 2, "text": "O tratamento de dados pessoais que possa afetar significativamente interesses e direitos fundamentais será caracterizado, dentre outras situações, naquelas em que a atividade de tratamento puder impedir o exercício de direitos ou a utilização de um serviço, assim como ocasionar danos materiais ou morais aos titulares, tais como discriminação, violação à integridade física, ao direito à imagem e à reputação, fraudes financeiras ou roubo de identidade"},
                {"n": 3, "text": "A ANPD poderá disponibilizar guias e orientações com o objetivo de auxiliar os agentes de tratamento de pequeno porte na avaliação do tratamento de alto risco"},
            ],
        },
        {
            "n": 5,
            "caput": "Caberá ao agente de tratamento de pequeno porte, quando solicitado pela ANPD, comprovar que se enquadra nas disposições do art. 2º e do art. 3º deste regulamento em até quinze dias",
        },
        {
            "n": 6,
            "caput": "A dispensa ou flexibilização das obrigações dispostas neste regulamento não isenta os agentes de tratamento de pequeno porte do cumprimento dos demais dispositivos da LGPD, inclusive das bases legais e dos princípios, de outras disposições legais, regulamentares e contratuais relativas à proteção de dados pessoais, bem como direitos dos titulares",
        },
        {
            "n": 7,
            "caput": "Os agentes de tratamento de pequeno porte devem disponibilizar informações sobre o tratamento de dados pessoais e atender às requisições dos titulares em conformidade com o disposto nos arts. 9º e 18 da LGPD, por meio:",
            "incisos": [
                {"n": 1, "text": "eletrônico"},
                {"n": 2, "text": "impresso"},
                {"n": 3, "text": "qualquer outro que assegure os direitos previstos na LGPD e o acesso facilitado às informações pelos titulares"},
            ],
        },
        {
            "n": 8,
            "caput": "Fica facultado aos agentes de tratamento de pequeno porte, inclusive àqueles que realizem tratamento de alto risco, organizarem-se por meio de entidades de representação da atividade empresarial, por pessoas jurídicas ou por pessoas naturais para fins de negociação, mediação e conciliação de reclamações apresentadas por titulares de dados",
        },
        {
            "n": 9,
            "caput": "Os agentes de tratamento de pequeno porte podem cumprir a obrigação de elaboração e manutenção de registro das operações de tratamento de dados pessoais, constante do art. 37 da LGPD, de forma simplificada",
            "parag_unico": "A ANPD fornecerá modelo para o registro simplificado de que trata o caput",
        },
        {
            "n": 10,
            "caput": "A ANPD disporá sobre flexibilização ou procedimento simplificado de comunicação de incidente de segurança para agentes de tratamento de pequeno porte, nos termos da regulamentação específica",
        },
        {
            "n": 11,
            "caput": "Os agentes de tratamento de pequeno porte não são obrigados a indicar o encarregado pelo tratamento de dados pessoais exigido no art. 41 da LGPD",
            "paragraphs": [
                {"n": 1, "text": "O agente de tratamento de pequeno porte que não indicar um encarregado deve disponibilizar um canal de comunicação com o titular de dados para atender o disposto no art. 41, § 2º, I da LGPD"},
                {"n": 2, "text": "A indicação de encarregado por parte dos agentes de tratamento de pequeno porte será considerada política de boas práticas e governança para fins do disposto no art. 52, §1º, IX da LGPD"},
            ],
        },
        {
            "n": 12,
            "caput": "Os agentes de tratamento de pequeno porte devem adotar medidas administrativas e técnicas essenciais e necessárias, com base em requisitos mínimos de segurança da informação para proteção dos dados pessoais, considerando, ainda, o nível de risco à privacidade dos titulares de dados e a realidade do agente de tratamento",
            "parag_unico": "O atendimento às recomendações e às boas práticas de prevenção e segurança divulgadas pela ANPD, inclusive por meio de guias orientativos, será considerado como observância ao disposto no art. 52, §1º, VIII da LGPD",
        },
        {
            "n": 13,
            "caput": "Os agentes de tratamento de pequeno porte podem estabelecer política simplificada de segurança da informação, que contemple requisitos essenciais e necessários para o tratamento de dados pessoais, com o objetivo de protegê-los de acessos não autorizados e de situações acidentais ou ilícitas de destruição, perda, alteração, comunicação ou qualquer forma de tratamento inadequado ou ilícito",
            "paragraphs": [
                {"n": 1, "text": "A política simplificada de segurança da informação deve levar em consideração os custos de implementação, bem como a estrutura, a escala e o volume das operações do agente de tratamento de pequeno porte"},
                {"n": 2, "text": "A ANPD considerará a existência de política simplificada de segurança da informação para fins do disposto no art. 6º, X e no art. 52, §1º, VIII e IX da LGPD"},
            ],
        },
        {
            "n": 14,
            "caput": "Aos agentes de tratamento de pequeno porte será concedido prazo em dobro:",
            "incisos": [
                {"n": 1, "text": "no atendimento das solicitações dos titulares referentes ao tratamento de seus dados pessoais, conforme previsto no art. 18, §§ 3º e 5º da LGPD, nos termos de regulamentação específica"},
                {"n": 2, "text": "no caso da comunicação, à ANPD e ao titular, da ocorrência de incidente de segurança que possa acarretar risco ou dano relevante aos titulares, nos termos do Regulamento de Comunicação de Incidente de Segurança, aprovado pela Resolução CD/ANPD nº 15, de 24 de abril de 2024"},
                {"n": 3, "text": "no fornecimento de declaração clara e completa, prevista no art. 19, II da LGPD"},
                {"n": 4, "text": "em relação aos prazos estabelecidos nos normativos próprios para a apresentação de informações, documentos, relatórios e registros solicitados pela ANPD a outros agentes de tratamento"},
            ],
            "parag_unico": "Os prazos não dispostos neste regulamento para agentes de tratamento de pequeno porte serão determinados por regulamentação específica",
        },
        {
            "n": 15,
            "caput": "Os agentes de tratamento de pequeno porte podem fornecer a declaração simplificada de que trata o art. 19, I, da LGPD no prazo de até quinze dias, contados da data do requerimento do titular",
        },
    ],
}


# ---------------------------------------------------------------------------
# Chunk emitter
# ---------------------------------------------------------------------------


def _chunk_base(doc_urn: str, partition: str, kind: str, label: str,
                text: str, parent_partition: str | None,
                nav: dict[str, str]) -> dict[str, Any]:
    return {
        "document_urn": doc_urn,
        "partition": partition,
        "kind": kind,
        "label": label,
        "text": text,
        "parent_partition": parent_partition,
        "nav": nav,
        "notes": [],
        "is_revoked": False,
        "urn": f"{doc_urn}~{partition}",
        "source": SOURCE_TAG,
        "source_pdf_sha256": "",  # no PDF — HTML source. Field kept for schema parity with anpd_pdf parser.
        "ingestion_method": INGESTION_METHOD,
        "ingestion_provenance": PROVENANCE,
    }


_ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
         "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX"]


def to_chunks(doc: dict[str, Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    doc_urn = doc["urn"]
    base_nav = doc["nav"]

    for art in doc["articles"]:
        art_part = f"art{art['n']}"
        # Caput — kind=artigo
        chunks.append(_chunk_base(
            doc_urn=doc_urn, partition=art_part,
            kind="artigo", label=f"Art. {art['n']}",
            text=art["caput"], parent_partition=None,
            nav={**base_nav, "artigo": f"Art. {art['n']}"},
        ))

        # Incisos directly under the artigo (the inciso-list is a definition
        # block, where incisos are the typed entries).
        for inc in art.get("incisos", []):
            inc_part = f"{art_part};inc{inc['n']}"
            inc_label = _ROMAN[inc["n"] - 1]
            chunks.append(_chunk_base(
                doc_urn=doc_urn, partition=inc_part,
                kind="inciso", label=inc_label,
                text=inc["text"], parent_partition=art_part,
                nav={**base_nav, "artigo": f"Art. {art['n']}",
                     "inciso": inc_label},
            ))
            # Alíneas inside this inciso
            for ali in inc.get("alineas", []):
                ali_part = f"{inc_part};ali-{ali['letter']}"
                chunks.append(_chunk_base(
                    doc_urn=doc_urn, partition=ali_part,
                    kind="alinea", label=ali["letter"],
                    text=ali["text"], parent_partition=inc_part,
                    nav={**base_nav, "artigo": f"Art. {art['n']}",
                         "inciso": inc_label, "alinea": ali["letter"]},
                ))

        # Parágrafos (numbered §)
        for par in art.get("paragraphs", []):
            par_part = f"{art_part};par{par['n']}"
            par_label = f"§ {par['n']}º"
            chunks.append(_chunk_base(
                doc_urn=doc_urn, partition=par_part,
                kind="paragrafo", label=par_label,
                text=par["text"], parent_partition=art_part,
                nav={**base_nav, "artigo": f"Art. {art['n']}",
                     "paragrafo": par_label},
            ))
            # Incisos nested under the parágrafo (Res. 1/2021 art. 8 § 2 has this)
            for inc in par.get("incisos", []):
                inc_part = f"{par_part};inc{inc['n']}"
                inc_label = _ROMAN[inc["n"] - 1]
                chunks.append(_chunk_base(
                    doc_urn=doc_urn, partition=inc_part,
                    kind="inciso", label=inc_label,
                    text=inc["text"], parent_partition=par_part,
                    nav={**base_nav, "artigo": f"Art. {art['n']}",
                         "paragrafo": par_label, "inciso": inc_label},
                ))

        # Parágrafo único (when only one paragraph; alternative form)
        if "parag_unico" in art:
            par_part = f"{art_part};par1"
            chunks.append(_chunk_base(
                doc_urn=doc_urn, partition=par_part,
                kind="paragrafo", label="Parágrafo único",
                text=art["parag_unico"], parent_partition=art_part,
                nav={**base_nav, "artigo": f"Art. {art['n']}",
                     "paragrafo": "Parágrafo único"},
            ))

    return chunks


def write_jsonl(chunks: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def main() -> int:
    for doc, filename in [
        (RES_1_2021, "anpd_res_1_2021.jsonl"),
        (RES_2_2022, "anpd_res_2_2022.jsonl"),
    ]:
        chunks = to_chunks(doc)
        out_path = OUT_DIR / filename
        write_jsonl(chunks, out_path)
        # Per-kind summary
        by_kind: dict[str, int] = {}
        for c in chunks:
            by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
        kinds_str = "  ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
        print(f"[{doc['urn']}]")
        print(f"  → {out_path.relative_to(PROJECT_ROOT)}")
        print(f"  {len(chunks)} chunks  {kinds_str}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
