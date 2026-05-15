"""Manual transcription of Resolução CD/ANPD nº 15/2024 → JSONL.

This script encodes (deterministically) what a Claude Code session
read from the source PDF on 2026-05-15 and structured into LCP-95
hierarchy. It is NOT a parser — running it doesn't read the PDF.
The PDF was read by the Read tool; the human-curated structure was
encoded here as a build artifact.

Why this exists (Phase 4.3.a — manual ingestion phase):
  - ANPD distributes resoluções as PDFs (sometimes scanned, often in
    multi-part bundles with notas técnicas attached). A robust parser
    for ANPD's layout is Phase 4.3.b (~1 week). For Phase 4.3.a we
    use Claude Code to transcribe each resolução once, with explicit
    metadata in every chunk so the future parser's output can be
    DIFF'd against this v0.
  - The output is stable: re-running this script produces byte-identical
    JSONL. Re-doing the transcription would require another Claude
    session + this script's structure to be edited.

Output: data/chunks/tier-3/anpd_res_15_2024.jsonl

Source: data/raw/tier-3/res_15_2024_full.pdf (11 pages, 236KB)
SHA-256: 6ebf628f0c0b1fa13342dfabb5be07e0371504021e5ffd158110c80d64627953
Hosted-by-mirror (MS): https://www.lgpd.ms.gov.br/wp-content/uploads/2024/05/REGULAMENTO-DE-COMUNICACAO-DE-INCIDENTE-DE-SEGURANCA-ABRIL-2024-ANPD-.pdf
Original DOU: 26/04/2024, Edição 81, Seção 1, p. 114

URN scheme (Phase 4.3.a.2 — synthetic for ANPD):
  urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2024-04-24;15

We index ONLY the Regulamento (anexo) articles, not the 3-article
resolução decree (which is purely administrative — "approves the
regulamento", "alters Res 2/2022 art.14;II", "enters in force").
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

# ----------------------------------------------------------------------------
# Source metadata — emitted on every chunk so Phase 4.3.b parser DIFF works
# ----------------------------------------------------------------------------

DOC_URN = "urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2024-04-24;15"
DOC_TITLE = "Resolução CD/ANPD nº 15/2024 — Regulamento de Comunicação de Incidente de Segurança"
SOURCE_SHA256 = "6ebf628f0c0b1fa13342dfabb5be07e0371504021e5ffd158110c80d64627953"
SOURCE_TAG = "claude-code-2026-05-15"
INGESTION_METHOD = "manual-transcription-v0"
INGESTION_PROVENANCE = "Read tool, single Claude session; PDF from lgpd.ms.gov.br mirror"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT / "data" / "chunks" / "tier-3" / "anpd_res_15_2024.jsonl"


# ----------------------------------------------------------------------------
# Chunk structure (mirrors rag_leis.chunks.Chunk, with audit-metadata fields)
# ----------------------------------------------------------------------------


@dataclass
class TierChunk:
    partition: str
    kind: str  # "artigo" | "paragrafo" | "inciso" | "alinea" | "item"
    label: str
    text: str
    parent_partition: str | None = None
    nav: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        urn = f"{DOC_URN}~{self.partition}"
        return {
            "document_urn": DOC_URN,
            "partition": self.partition,
            "kind": self.kind,
            "label": self.label,
            "text": self.text,
            "parent_partition": self.parent_partition,
            "nav": self.nav,
            "notes": [],
            "is_revoked": False,
            "urn": urn,
            # Phase 4.3.a audit-metadata — distinguishes manual ingestion
            "source": SOURCE_TAG,
            "source_pdf_sha256": SOURCE_SHA256,
            "ingestion_method": INGESTION_METHOD,
            "ingestion_provenance": INGESTION_PROVENANCE,
        }


# Convenience constructors that compute partition+nav from context
def artigo(num: str, text: str, nav: dict) -> TierChunk:
    return TierChunk(
        partition=f"art{num}",
        kind="artigo",
        label=f"Art. {num}",
        text=text,
        parent_partition=None,
        nav=nav,
    )


def paragrafo(art_num: str, par_num: str, text: str, nav: dict, label: str | None = None) -> TierChunk:
    return TierChunk(
        partition=f"art{art_num};par{par_num}",
        kind="paragrafo",
        label=label or f"§ {par_num}º",
        text=text,
        parent_partition=f"art{art_num}",
        nav=nav,
    )


def paragrafo_unico(art_num: str, text: str, nav: dict) -> TierChunk:
    """Parágrafo único uses `par1` partition (existing-corpus convention).
    Articles with parágrafo único never have numbered §§ — no collision."""
    return TierChunk(
        partition=f"art{art_num};par1",
        kind="paragrafo",
        label="Parágrafo único",
        text=text,
        parent_partition=f"art{art_num}",
        nav=nav,
    )


def inciso(parent: str, num_roman: str, text: str, nav: dict) -> TierChunk:
    partition = f"{parent};inc{_roman_to_int(num_roman)}"
    return TierChunk(
        partition=partition,
        kind="inciso",
        label=num_roman,
        text=text,
        parent_partition=parent,
        nav=nav,
    )


_ROMAN_MAP = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
    "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
}


def _roman_to_int(s: str) -> int:
    return _ROMAN_MAP[s]


# ----------------------------------------------------------------------------
# Content (read from PDF on 2026-05-15)
# ----------------------------------------------------------------------------


def build_chunks() -> list[TierChunk]:
    """Build the full chunk list. Order = reading order in the PDF.

    Nav: each chunk gets `{titulo, capitulo, secao}` where applicable.
    Top-level capítulos are the only nav.titulo; seções nest under.
    """
    chunks: list[TierChunk] = []

    # Document title for nav consistency
    title = "RESOLUÇÃO CD/ANPD Nº 15, DE 24 DE ABRIL DE 2024 — ANEXO: REGULAMENTO DE COMUNICAÇÃO DE INCIDENTE DE SEGURANÇA"

    # ========================================================================
    # CAPÍTULO I — DISPOSIÇÕES PRELIMINARES
    # ========================================================================
    nav_cap1 = {"titulo": title, "capitulo": "CAPÍTULO I — DISPOSIÇÕES PRELIMINARES"}

    chunks.append(artigo(
        "1",
        "Este Regulamento tem por objetivo estabelecer os procedimentos para "
        "Comunicação de Incidente de Segurança, que possa acarretar risco ou "
        "dano relevante aos titulares, nos termos do art. 48 da Lei nº 13.709, "
        "de 14 de agosto de 2018 - Lei Geral de Proteção de Dados Pessoais (LGPD).",
        nav_cap1,
    ))

    chunks.append(artigo(
        "2",
        "São objetivos deste Regulamento:",
        nav_cap1,
    ))
    art2_incs = [
        ("I", "proteger os direitos dos titulares;"),
        ("II", "assegurar a adoção das medidas necessárias para mitigar ou reverter os efeitos dos prejuízos gerados;"),
        ("III", "assegurar a efetividade do princípio da responsabilização e da prestação de contas pelos agentes de tratamento;"),
        ("IV", "promover a adoção de regras de boas práticas, de governança, de medidas de prevenção e segurança adequadas;"),
        ("V", "estimular a promoção da cultura de proteção de dados pessoais;"),
        ("VI", "garantir que os agentes de tratamento atuem de forma transparente e estabeleçam uma relação de confiança com o titular; e"),
        ("VII", "fornecer subsídios para as atividades regulatória, fiscalizatória e sancionatória da Autoridade Nacional de Proteção de Dados (ANPD)."),
    ]
    for roman, txt in art2_incs:
        chunks.append(inciso("art2", roman, txt, nav_cap1))

    # ========================================================================
    # CAPÍTULO II — DAS DEFINIÇÕES
    # ========================================================================
    nav_cap2 = {"titulo": title, "capitulo": "CAPÍTULO II — DAS DEFINIÇÕES"}

    chunks.append(artigo(
        "3",
        "Para efeitos deste Regulamento, são adotadas as seguintes definições:",
        nav_cap2,
    ))
    art3_incs = [
        ("I", "ampla divulgação do incidente em meios de comunicação: providência que pode ser determinada pela ANPD ao controlador, nos termos do art. 48, § 2º, I, da LGPD, no âmbito do processo de comunicação de incidente de segurança, como a publicação no sítio eletrônico, nas redes sociais do controlador ou em outros meios de comunicação;"),
        ("II", "autenticidade: propriedade pela qual se assegura que a informação foi produzida, expedida, modificada ou destruída por uma determinada pessoa física, equipamento, sistema, órgão ou entidade;"),
        ("III", "categoria de dados pessoais: classificação dos dados pessoais de acordo com o contexto de sua utilização, tais como dados de identificação pessoal, dados de autenticação em sistemas, dados financeiros;"),
        ("IV", "comunicação de incidente de segurança: ato do controlador que comunica à ANPD e ao titular de dados a ocorrência de incidente de segurança que possa acarretar risco ou dano relevante aos titulares;"),
        ("V", "confidencialidade: propriedade pela qual se assegura que o dado pessoal não esteja disponível ou não seja revelado a pessoas, empresas, sistemas, órgãos ou entidades não autorizados;"),
        ("VI", "dado de autenticação em sistemas: qualquer dado pessoal utilizado como credencial para determinar o acesso a um sistema ou para confirmar a identificação de um usuário, como contas de login, tokens e senhas;"),
        ("VII", "dado financeiro: dado pessoal relacionado às transações financeiras do titular, inclusive para contratação de serviços e aquisição de produtos;"),
        ("VIII", "dado pessoal afetado: dado pessoal cuja confidencialidade, integridade, disponibilidade ou autenticidade tenha sido comprometida em um incidente de segurança;"),
        ("IX", "dado protegido por sigilo legal ou judicial: dado pessoal cujo sigilo decorra de norma jurídica ou decisão judicial;"),
        ("X", "dado protegido por sigilo profissional: dado pessoal cujo sigilo decorra do exercício de função, ministério, ofício ou profissão, e cuja revelação possa produzir dano a outrem;"),
        ("XI", "disponibilidade: propriedade pela qual se assegura que o dado pessoal esteja acessível e utilizável, sob demanda, por uma pessoa natural ou determinado sistema, órgão ou entidade devidamente autorizados;"),
        ("XII", "incidente de segurança: qualquer evento adverso confirmado, relacionado à violação das propriedades de confidencialidade, integridade, disponibilidade e autenticidade da segurança de dados pessoais;"),
        ("XIII", "integridade: propriedade pela qual se assegura que o dado pessoal não foi modificado ou destruído de maneira não autorizada ou acidental;"),
        ("XIV", "medidas de segurança: medidas técnicas e/ou administrativas adotadas para proteger os dados pessoais de acessos não autorizados e de situações acidentais ou ilícitas de destruição, perda, alteração, comunicação ou difusão;"),
        ("XV", "natureza dos dados pessoais: classificação de dados pessoais em gerais ou sensíveis;"),
        ("XVI", "procedimento de apuração de incidente de segurança: procedimento instaurado pela ANPD para apurar a ocorrência de incidente de segurança que não tenha sido comunicado pelo controlador;"),
        ("XVII", "procedimento de comunicação de incidente de segurança: procedimento instaurado no âmbito da ANPD após o recebimento de comunicação de incidente de segurança;"),
        ("XVIII", "processo de comunicação de incidente de segurança: processo administrativo instaurado no âmbito da ANPD que abrange o procedimento de apuração incidente de segurança e o procedimento de comunicação de incidente de segurança; e"),
        ("XIX", "relatório de tratamento de incidente: documento fornecido pelo controlador que contém cópias, em meio físico ou digital, de dados e informações relevantes para descrever o incidente e as providências adotadas para reverter ou mitigar os seus efeitos."),
    ]
    for roman, txt in art3_incs:
        chunks.append(inciso("art3", roman, txt, nav_cap2))

    # ========================================================================
    # CAPÍTULO III — DA COMUNICAÇÃO DE INCIDENTE DE SEGURANÇA
    # ========================================================================
    cap3 = "CAPÍTULO III — DA COMUNICAÇÃO DE INCIDENTE DE SEGURANÇA"
    sec3_1 = "Seção I — Dos Critérios para Comunicação de Incidente de Segurança"
    sec3_2 = "Seção II — Da Comunicação de Incidente de Segurança à ANPD"
    sec3_3 = "Seção III — Da Comunicação de Incidente de Segurança ao Titular"

    nav_cap3_sec1 = {"titulo": title, "capitulo": cap3, "secao": sec3_1}
    nav_cap3_sec2 = {"titulo": title, "capitulo": cap3, "secao": sec3_2}
    nav_cap3_sec3 = {"titulo": title, "capitulo": cap3, "secao": sec3_3}

    # Art. 4 — caput
    chunks.append(artigo(
        "4",
        "O controlador deverá comunicar à ANPD e ao titular a ocorrência de "
        "incidente de segurança que possa acarretar risco ou dano relevante "
        "aos titulares.",
        nav_cap3_sec1,
    ))

    # Art. 5 — caput + 6 incs + §§1-3
    chunks.append(artigo(
        "5",
        "O incidente de segurança pode acarretar risco ou dano relevante aos "
        "titulares quando puder afetar significativamente interesses e direitos "
        "fundamentais dos titulares e, cumulativamente, envolver, pelo menos, "
        "um dos seguintes critérios:",
        nav_cap3_sec1,
    ))
    for roman, txt in [
        ("I", "dados pessoais sensíveis;"),
        ("II", "dados de crianças, de adolescentes ou de idosos;"),
        ("III", "dados financeiros;"),
        ("IV", "dados de autenticação em sistemas;"),
        ("V", "dados protegidos por sigilo legal, judicial ou profissional; ou"),
        ("VI", "dados em larga escala."),
    ]:
        chunks.append(inciso("art5", roman, txt, nav_cap3_sec1))
    chunks.append(paragrafo("5", "1", (
        "O incidente de segurança que possa afetar significativamente "
        "interesses e direitos fundamentais será caracterizado, dentre outras "
        "situações, naquelas em que a atividade de tratamento puder impedir o "
        "exercício de direitos ou a utilização de um serviço, assim como "
        "ocasionar danos materiais ou morais aos titulares, tais como "
        "discriminação, violação à integridade física, ao direito à imagem e "
        "à reputação, fraudes financeiras ou roubo de identidade."
    ), nav_cap3_sec1))
    chunks.append(paragrafo("5", "2", (
        "Considera-se incidente com dados em larga escala aquele que abranger "
        "número significativo de titulares, considerando, ainda, o volume de "
        "dados envolvidos, bem como a duração, a frequência e a extensão "
        "geográfica de localização dos titulares."
    ), nav_cap3_sec1))
    chunks.append(paragrafo("5", "3", (
        "A ANPD poderá publicar orientações com o objetivo de auxiliar os "
        "agentes de tratamento na avaliação do incidente que possa acarretar "
        "risco ou dano relevante aos titulares."
    ), nav_cap3_sec1))

    # Art. 6 — caput (3 dias úteis prazo!) + 8 paragrafos, §2 has 12 incs
    chunks.append(artigo(
        "6",
        "A comunicação de incidente de segurança à ANPD deverá ser realizada "
        "pelo controlador no prazo de três dias úteis, ressalvada a "
        "existência de prazo para comunicação previsto em legislação específica.",
        nav_cap3_sec2,
    ))
    chunks.append(paragrafo("6", "1", (
        "O prazo a que se refere o caput será contado do conhecimento pelo "
        "controlador de que o incidente afetou dados pessoais."
    ), nav_cap3_sec2))
    chunks.append(paragrafo("6", "2", (
        "A comunicação de incidente de segurança deverá conter as seguintes informações:"
    ), nav_cap3_sec2))
    art6_par2_incs = [
        ("I", "a descrição da natureza e da categoria de dados pessoais afetados;"),
        ("II", "o número de titulares afetados, discriminando, quando aplicável, o número de crianças, de adolescentes ou de idosos;"),
        ("III", "as medidas técnicas e de segurança utilizadas para a proteção dos dados pessoais, adotadas antes e após o incidente, observados os segredos comercial e industrial;"),
        ("IV", "os riscos relacionados ao incidente com identificação dos possíveis impactos aos titulares;"),
        ("V", "os motivos da demora, no caso de a comunicação não ter sido realizada no prazo previsto no caput deste artigo;"),
        ("VI", "as medidas que foram ou que serão adotadas para reverter ou mitigar os efeitos do incidente sobre os titulares;"),
        ("VII", "a data da ocorrência do incidente, quando possível determiná-la, e a de seu conhecimento pelo controlador;"),
        ("VIII", "os dados do encarregado ou de quem represente o controlador;"),
        ("IX", "a identificação do controlador e, se for o caso, declaração de que se trata de agente de tratamento de pequeno porte;"),
        ("X", "a identificação do operador, quando aplicável;"),
        ("XI", "a descrição do incidente, incluindo a causa principal, caso seja possível identificá-la; e"),
        ("XII", "o total de titulares cujos dados são tratados nas atividades de tratamento afetadas pelo incidente."),
    ]
    for roman, txt in art6_par2_incs:
        chunks.append(inciso("art6;par2", roman, txt, nav_cap3_sec2))
    chunks.append(paragrafo("6", "3", (
        "As informações poderão ser complementadas, de maneira fundamentada, "
        "no prazo de vinte dias úteis, a contar da data da comunicação."
    ), nav_cap3_sec2))
    chunks.append(paragrafo("6", "4", (
        "A comunicação de incidente de segurança deverá ocorrer por meio de "
        "formulário eletrônico disponibilizado pela ANPD."
    ), nav_cap3_sec2))
    chunks.append(paragrafo("6", "5", (
        "A comunicação de incidente de segurança deverá ser realizada pelo "
        "controlador, por meio do encarregado, acompanhada de documento "
        "comprobatório de vínculo contratual, empregatício ou funcional, ou "
        "por meio de representante constituído, acompanhada de instrumento "
        "com poderes de representação junto à ANPD."
    ), nav_cap3_sec2))
    chunks.append(paragrafo("6", "6", (
        "Os documentos de que trata o § 5º deverão ser apresentados juntamente "
        "com a comunicação do incidente de segurança, no prazo previsto no "
        "caput deste artigo."
    ), nav_cap3_sec2))
    chunks.append(paragrafo("6", "7", (
        "No caso de descumprimento do previsto no § 6º, a ANPD poderá apurar "
        "a ocorrência do incidente de segurança por meio do procedimento de "
        "apuração de incidente de segurança."
    ), nav_cap3_sec2))
    chunks.append(paragrafo("6", "8", (
        "Os prazos constantes no caput e no § 3º deste artigo são contados em "
        "dobro para os agentes de pequeno porte, nos termos do disposto no "
        "Regulamento de aplicação da Lei nº 13.709, de 14 de agosto de 2018, "
        "Lei Geral de Proteção de Dados Pessoais (LGPD), aos agentes de "
        "tratamento de pequeno porte, aprovado pela Resolução CD/ANPD nº 2, "
        "de 27 de janeiro de 2022."
    ), nav_cap3_sec2))

    # Art. 7 — caput
    chunks.append(artigo(
        "7",
        "Cabe ao controlador solicitar à ANPD, de maneira fundamentada, o "
        "sigilo de informações protegidas por lei, indicando aquelas cujo "
        "acesso deverá ser restringido, a exemplo das relativas à sua "
        "atividade empresarial cuja divulgação possa representar violação de "
        "segredo comercial ou industrial.",
        nav_cap3_sec2,
    ))

    # Art. 8 — caput
    chunks.append(artigo(
        "8",
        "A ANPD poderá, a qualquer tempo, solicitar informações adicionais ao "
        "controlador, referentes ao incidente de segurança, inclusive o "
        "registro das operações de tratamento dos dados pessoais afetados "
        "pelo incidente, o relatório de impacto à proteção de dados pessoais "
        "(RIPD) e o relatório de tratamento do incidente, estabelecendo "
        "prazo para o envio das informações.",
        nav_cap3_sec2,
    ))

    # Art. 9 — caput + 7 incs + §§1-6
    chunks.append(artigo(
        "9",
        "A comunicação de incidente de segurança ao titular deverá ser "
        "realizada pelo controlador no prazo de três dias úteis contados do "
        "conhecimento pelo controlador de que o incidente afetou dados "
        "pessoais, e deverá conter as seguintes informações:",
        nav_cap3_sec3,
    ))
    for roman, txt in [
        ("I", "a descrição da natureza e da categoria de dados pessoais afetados;"),
        ("II", "as medidas técnicas e de segurança utilizadas para a proteção dos dados, observados os segredos comercial e industrial;"),
        ("III", "os riscos relacionados ao incidente com identificação dos possíveis impactos aos titulares;"),
        ("IV", "os motivos da demora, no caso de a comunicação não ter sido feita no prazo do caput deste artigo;"),
        ("V", "as medidas que foram ou que serão adotadas para reverter ou mitigar os efeitos do incidente, quando cabíveis;"),
        ("VI", "a data do conhecimento do incidente de segurança; e"),
        ("VII", "o contato para obtenção de informações e, quando aplicável, os dados de contato do encarregado."),
    ]:
        chunks.append(inciso("art9", roman, txt, nav_cap3_sec3))
    chunks.append(paragrafo("9", "1", (
        "A comunicação do incidente aos titulares de dados deverá atender aos seguintes critérios:"
    ), nav_cap3_sec3))
    chunks.append(inciso("art9;par1", "I", "fazer uso de linguagem simples e de fácil entendimento; e", nav_cap3_sec3))
    chunks.append(inciso("art9;par1", "II", "ocorrer de forma direta e individualizada, caso seja possível identificá-los.", nav_cap3_sec3))
    chunks.append(paragrafo("9", "2", (
        "Considera-se comunicação de forma direta e individualizada aquela "
        "realizada pelos meios usualmente utilizados pelo controlador para "
        "contatar o titular, tais como telefone, e-mail, mensagem eletrônica "
        "ou carta."
    ), nav_cap3_sec3))
    chunks.append(paragrafo("9", "3", (
        "Caso a comunicação direta e individualizada mostre-se inviável ou "
        "não seja possível identificar, parcial ou integralmente, os "
        "titulares afetados, o controlador deverá comunicar a ocorrência do "
        "incidente, no prazo e com as informações definidas no caput, pelos "
        "meios de divulgação disponíveis, tais como seu sítio eletrônico, "
        "aplicativos, suas mídias sociais e canais de atendimento ao titular, "
        "de modo que a comunicação permita o conhecimento amplo, com direta "
        "e fácil visualização, pelo período de, no mínimo, três meses."
    ), nav_cap3_sec3))
    chunks.append(paragrafo("9", "4", (
        "O controlador deverá juntar ao processo de comunicação de incidente "
        "uma declaração de que foi realizada a comunicação aos titulares, "
        "constando os meios de comunicação ou divulgação utilizados, em até "
        "três dias úteis, contados do término do prazo de que trata o caput "
        "deste artigo."
    ), nav_cap3_sec3))
    chunks.append(paragrafo("9", "5", (
        "Poderá ser considerada boa prática, para fins do disposto no art. "
        "52, § 1º, IX, da LGPD, a inclusão, na comunicação ao titular, de "
        "recomendações aptas a reverter ou mitigar os efeitos do incidente."
    ), nav_cap3_sec3))
    chunks.append(paragrafo("9", "6", (
        "O prazo constante no caput deste artigo é contado em dobro para os "
        "agentes de pequeno porte, nos termos do disposto no Regulamento de "
        "aplicação da Lei nº 13.709, de 14 de agosto de 2018, Lei Geral de "
        "Proteção de Dados Pessoais (LGPD) aos agentes de tratamento de "
        "pequeno porte, aprovado pela Resolução CD/ANPD nº 2, de 27 de janeiro "
        "de 2022."
    ), nav_cap3_sec3))

    # ========================================================================
    # CAPÍTULO IV — DO REGISTRO DO INCIDENTE DE SEGURANÇA
    # ========================================================================
    nav_cap4 = {"titulo": title, "capitulo": "CAPÍTULO IV — DO REGISTRO DO INCIDENTE DE SEGURANÇA"}

    chunks.append(artigo(
        "10",
        "O controlador deverá manter o registro do incidente de segurança, "
        "inclusive daquele não comunicado à ANPD e aos titulares, pelo prazo "
        "mínimo de cinco anos, contado a partir da data do registro, exceto "
        "se constatadas obrigações adicionais que demandem maior prazo de "
        "manutenção.",
        nav_cap4,
    ))
    chunks.append(paragrafo("10", "1", "O registro do incidente deverá conter, no mínimo:", nav_cap4))
    for roman, txt in [
        ("I", "a data de conhecimento do incidente;"),
        ("II", "a descrição geral das circunstâncias em que o incidente ocorreu;"),
        ("III", "a natureza e a categoria de dados afetados;"),
        ("IV", "o número de titulares afetados;"),
        ("V", "a avaliação do risco e os possíveis danos aos titulares;"),
        ("VI", "as medidas de correção e mitigação dos efeitos do incidente, quando aplicável;"),
        ("VII", "a forma e o conteúdo da comunicação, se o incidente tiver sido comunicado à ANPD e aos titulares; e"),
        ("VIII", "os motivos da ausência de comunicação, quando for o caso."),
    ]:
        chunks.append(inciso("art10;par1", roman, txt, nav_cap4))
    chunks.append(paragrafo("10", "2", (
        "Os prazos de guarda previstos neste artigo não se aplicam às "
        "entidades previstas no art. 23 da LGPD, desde que sejam observadas "
        "as regras aplicáveis aos documentos de guarda permanente previstas "
        "na tabela de temporalidade própria ou definidas pelo Conselho "
        "Nacional de Arquivos."
    ), nav_cap4))

    # ========================================================================
    # CAPÍTULO V — DO PROCESSO DE COMUNICAÇÃO DE INCIDENTE DE SEGURANÇA
    # ========================================================================
    cap5 = "CAPÍTULO V — DO PROCESSO DE COMUNICAÇÃO DE INCIDENTE DE SEGURANÇA"
    sec5_1 = "Seção I — Das Disposições Gerais"
    sec5_2 = "Seção II — Do Procedimento de Apuração de Incidente de Segurança"
    sec5_3 = "Seção III — Do Procedimento de Comunicação de Incidente de Segurança"
    sec5_4 = "Seção IV — Da Extinção do Processo de Comunicação de Incidente de Segurança"

    nav_cap5_sec1 = {"titulo": title, "capitulo": cap5, "secao": sec5_1}
    nav_cap5_sec2 = {"titulo": title, "capitulo": cap5, "secao": sec5_2}
    nav_cap5_sec3 = {"titulo": title, "capitulo": cap5, "secao": sec5_3}
    nav_cap5_sec4 = {"titulo": title, "capitulo": cap5, "secao": sec5_4}

    # Art. 11
    chunks.append(artigo(
        "11",
        "O processo de comunicação de incidente de segurança tem por objeto a "
        "fiscalização de atos relacionados ao tratamento e resposta ao "
        "incidente que possa acarretar risco ou dano relevante aos titulares "
        "de dados, a fim de salvaguardar os direitos dos titulares.",
        nav_cap5_sec1,
    ))
    chunks.append(paragrafo_unico("11", (
        "Aplicam-se ao processo de comunicação de incidente de segurança "
        "regido por este Regulamento, no que couber, as disposições do "
        "Regulamento do Processo de Fiscalização e do Processo Administrativo "
        "Sancionador, aprovado pela Resolução CD/ANPD nº 01, de 28 de outubro "
        "de 2021."
    ), nav_cap5_sec1))

    # Art. 12
    chunks.append(artigo(
        "12",
        "A ANPD poderá, a qualquer momento, realizar auditorias ou inspeções "
        "junto aos agentes de tratamento, ou determinar a sua realização, "
        "para coletar informações complementares ou validar as informações "
        "recebidas, com o objetivo de subsidiar as decisões no âmbito do "
        "processo de comunicação de incidente de segurança.",
        nav_cap5_sec1,
    ))

    # Art. 13 — caput + I-II
    chunks.append(artigo("13", "O processo de comunicação de incidente de segurança inicia-se:", nav_cap5_sec1))
    chunks.append(inciso("art13", "I", "de ofício, no caso de procedimento de apuração de incidente de segurança; ou", nav_cap5_sec1))
    chunks.append(inciso("art13", "II", (
        "com o recebimento da comunicação, devidamente formalizada, na forma "
        "do art. 6º, §5º, no caso de procedimento de comunicação de incidente "
        "de segurança."
    ), nav_cap5_sec1))

    # Art. 14
    chunks.append(artigo(
        "14",
        "Os processos de comunicação de incidente de segurança poderão ser "
        "analisados de forma agregada, e as eventuais providências deles "
        "decorrentes poderão ser adotadas de forma padronizada, em "
        "conformidade com o planejamento da atividade de fiscalização e os "
        "critérios de priorização definidos no Relatório de Ciclo de "
        "Monitoramento de que trata o art. 20 do Regulamento do Processo de "
        "Fiscalização e do Processo Administrativo Sancionador no âmbito da "
        "Autoridade Nacional de Proteção de Dados, aprovado pela Resolução "
        "CD/ANPD nº 1, de 28 de outubro de 2021.",
        nav_cap5_sec1,
    ))

    # Art. 15 — caput + parágrafo único
    chunks.append(artigo(
        "15",
        "No curso do processo de comunicação de incidente de segurança, a "
        "ANPD poderá determinar ao controlador, com ou sem a sua prévia "
        "manifestação, a adoção imediata de medidas preventivas necessárias "
        "para salvaguardar direitos dos titulares, a fim de prevenir, mitigar "
        "ou reverter os efeitos do incidente e evitar a ocorrência de dano "
        "grave e irreparável ou de difícil reparação.",
        nav_cap5_sec1,
    ))
    chunks.append(paragrafo_unico("15", (
        "A ANPD poderá fixar multa diária para assegurar o cumprimento da "
        "determinação prevista no caput, na forma do Regulamento de "
        "Dosimetria e Aplicação de Sanções Administrativas, aprovado pela "
        "Resolução CD/ANPD nº 4, de 24 de fevereiro de 2023."
    ), nav_cap5_sec1))

    # Art. 16 — caput + §§ 1-2
    chunks.append(artigo(
        "16",
        "A ANPD poderá apurar, por meio do procedimento de apuração de "
        "incidente de segurança, a ocorrência de incidentes que possam "
        "acarretar risco ou dano relevante aos titulares, não comunicados "
        "pelo controlador, de que venha a tomar conhecimento.",
        nav_cap5_sec2,
    ))
    chunks.append(paragrafo("16", "1", (
        "A ANPD poderá requisitar ao controlador informações para apurar a "
        "ocorrência do incidente de segurança."
    ), nav_cap5_sec2))
    chunks.append(paragrafo("16", "2", (
        "A ANPD avaliará a ocorrência do incidente por meio dos critérios "
        "dispostos no art. 5º deste Regulamento."
    ), nav_cap5_sec2))

    # Art. 17 — caput + §§ 1-2
    chunks.append(artigo(
        "17",
        "Constatada a ocorrência de incidente de segurança, a ANPD "
        "determinará ao controlador o envio da comunicação à Autoridade e "
        "aos titulares, observados os prazos e condições descritos nos arts. "
        "6º e 9º deste Regulamento, respectivamente.",
        nav_cap5_sec2,
    ))
    chunks.append(paragrafo("17", "1", (
        "A ANPD poderá, ainda, instaurar processo administrativo sancionador "
        "para apurar o descumprimento do previsto nos arts. 6º e 9º deste "
        "Regulamento."
    ), nav_cap5_sec2))
    chunks.append(paragrafo("17", "2", (
        "Realizada a comunicação de incidente de segurança, na forma do "
        "caput, aplicar-se-á o procedimento de comunicação de incidente de "
        "segurança estabelecido na Seção III."
    ), nav_cap5_sec2))

    # Art. 18 — caput + parágrafo único
    chunks.append(artigo(
        "18",
        "O procedimento de comunicação de incidente de segurança será "
        "iniciado com o recebimento da comunicação do incidente pela ANPD, "
        "devidamente formalizada, na forma do art. 6º., §5º.",
        nav_cap5_sec3,
    ))
    chunks.append(paragrafo_unico("18", (
        "A comunicação do incidente será recebida, exclusivamente, por meio "
        "de canal específico, conforme orientação publicada no sítio "
        "eletrônico da ANPD."
    ), nav_cap5_sec3))

    # Art. 19 — caput + I-II + §§ 1-7 (§5 has I-III)
    chunks.append(artigo(
        "19",
        "Após avaliar a gravidade do incidente de segurança, a ANPD poderá "
        "determinar ao controlador a adoção de providências para a "
        "salvaguarda dos direitos dos titulares, tais como:",
        nav_cap5_sec3,
    ))
    chunks.append(inciso("art19", "I", "ampla divulgação do incidente em meios de comunicação; e", nav_cap5_sec3))
    chunks.append(inciso("art19", "II", "medidas para reverter ou mitigar os efeitos do incidente.", nav_cap5_sec3))
    chunks.append(paragrafo("19", "1", (
        "A gravidade do incidente será avaliada com base nas informações "
        "obtidas e nos critérios de que trata o art. 5º deste Regulamento."
    ), nav_cap5_sec3))
    chunks.append(paragrafo("19", "2", "As providências citadas no caput devem estar diretamente relacionadas ao incidente.", nav_cap5_sec3))
    chunks.append(paragrafo("19", "3", (
        "A ANPD poderá determinar ampla divulgação do incidente em meios de "
        "comunicação, às expensas do controlador, para a salvaguarda dos "
        "direitos dos titulares, nos termos do art. 48, § 2º, I, da LGPD, "
        "quando a comunicação realizada pelo controlador mostrar-se "
        "insuficiente para alcançar parcela significativa dos titulares "
        "afetados pelo incidente."
    ), nav_cap5_sec3))
    chunks.append(paragrafo("19", "4", (
        "A ampla divulgação do incidente em meios de comunicação deverá ser "
        "compatível com a abrangência de atuação do controlador e a "
        "localização dos titulares dos dados pessoais afetados no incidente."
    ), nav_cap5_sec3))
    chunks.append(paragrafo("19", "5", (
        "A ampla divulgação do incidente poderá ser viabilizada em meio "
        "físico ou digital, considerada sempre a necessidade de se atingir o "
        "maior número possível de titulares afetados, admitidos os seguintes "
        "meios de veiculação:"
    ), nav_cap5_sec3))
    chunks.append(inciso("art19;par5", "I", "mídia escrita impressa;", nav_cap5_sec3))
    chunks.append(inciso("art19;par5", "II", "radiodifusão de sons e de sons e imagens; ou", nav_cap5_sec3))
    chunks.append(inciso("art19;par5", "III", "transmissão de informações pela Internet.", nav_cap5_sec3))
    chunks.append(paragrafo("19", "6", (
        "A ampla divulgação do incidente não se confunde com a sanção de "
        "publicização da infração de que trata no art. 52, IV, da LGPD."
    ), nav_cap5_sec3))
    chunks.append(paragrafo("19", "7", (
        "Na determinação das medidas para reverter ou mitigar os efeitos do "
        "incidente, serão considerados aquelas que possam garantir a "
        "confidencialidade, a integridade, a disponibilidade e a "
        "autenticidade dos dados pessoais afetados, bem como minimizar os "
        "efeitos decorrentes do incidente para os titulares."
    ), nav_cap5_sec3))

    # Art. 20
    chunks.append(artigo(
        "20",
        "Como medida de transparência ativa, a ANPD poderá divulgar, em seu "
        "sítio eletrônico, informações estatísticas agregadas relativas aos "
        "incidentes de segurança.",
        nav_cap5_sec3,
    ))

    # Art. 21
    chunks.append(artigo(
        "21",
        "A ANPD poderá instaurar processo administrativo sancionador caso o "
        "controlador não adote as medidas para reverter ou mitigar os "
        "efeitos do incidente de segurança no prazo e nas condições "
        "determinadas pela Autoridade.",
        nav_cap5_sec3,
    ))

    # Art. 22
    chunks.append(artigo(
        "22",
        "As providências descritas no art. 19 deste Regulamento não "
        "constituem sanções ao agente regulado, sendo equiparadas às medidas "
        "decorrentes da atividade preventiva, nos termos do Regulamento do "
        "Processo de Fiscalização e do Processo Administrativo Sancionador "
        "no âmbito da Autoridade Nacional de Proteção de Dados, aprovado "
        "pela Resolução CD/ANPD nº 1, de 28 de outubro de 2021.",
        nav_cap5_sec3,
    ))

    # Art. 23 — caput + I-V + parágrafo único
    chunks.append(artigo(
        "23",
        "O processo de comunicação de incidente de segurança será declarado "
        "extinto nas seguintes hipóteses:",
        nav_cap5_sec4,
    ))
    for roman, txt in [
        ("I", "caso não sejam identificadas evidências suficientes da ocorrência do incidente, ressalvada a possibilidade de reabertura caso surjam fatos novos;"),
        ("II", "caso a ANPD considere que o incidente não possui potencial para acarretar risco ou dano relevante aos titulares, nos termos do art. 5º deste Regulamento;"),
        ("III", "caso o incidente não envolva dados pessoais;"),
        ("IV", "caso tenham sido tomadas todas as medidas adicionais para mitigação ou reversão dos efeitos gerados; ou"),
        ("V", "realização da comunicação aos titulares e adoção das providências pertinentes pelo controlador, em conformidade com a LGPD, as disposições deste Regulamento e as determinações da ANPD."),
    ]:
        chunks.append(inciso("art23", roman, txt, nav_cap5_sec4))
    chunks.append(paragrafo_unico("23", (
        "Na hipótese do inciso II do caput, mesmo com a declaração da "
        "extinção do processo de comunicação de incidente de segurança, a "
        "ANPD poderá determinar a adoção de medidas de segurança "
        "diretamente relacionadas ao incidente, com o intuito de "
        "salvaguardar os direitos dos titulares."
    ), nav_cap5_sec4))

    # ========================================================================
    # CAPÍTULO VI — DAS DISPOSIÇÕES FINAIS
    # ========================================================================
    nav_cap6 = {"titulo": title, "capitulo": "CAPÍTULO VI — DAS DISPOSIÇÕES FINAIS"}

    chunks.append(artigo(
        "24",
        "As disposições constantes deste Regulamento aplicam-se aos "
        "processos de comunicação de incidentes de segurança em curso "
        "quando da sua entrada em vigor, respeitados os atos processuais "
        "praticados e consolidados.",
        nav_cap6,
    ))

    return chunks


# ----------------------------------------------------------------------------
# Build + write + verify
# ----------------------------------------------------------------------------


def main() -> None:
    chunks = build_chunks()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")
    print(f"Wrote {len(chunks)} chunks → {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")

    # Per-kind summary
    from collections import Counter
    kinds = Counter(c.kind for c in chunks)
    for k, n in sorted(kinds.items()):
        print(f"  {k}: {n}")

    # Sanity: SHA256 of source PDF still matches
    pdf_path = PROJECT_ROOT / "data" / "raw" / "tier-3" / "res_15_2024_full.pdf"
    actual_sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assert actual_sha == SOURCE_SHA256, (
        f"PDF SHA-256 drift! file={actual_sha} hardcoded={SOURCE_SHA256}\n"
        f"This means the PDF was re-downloaded/changed; re-verify content "
        f"and update the hardcoded hash."
    )
    print(f"\nSource PDF SHA-256 verified: {SOURCE_SHA256[:16]}...")


if __name__ == "__main__":
    main()
