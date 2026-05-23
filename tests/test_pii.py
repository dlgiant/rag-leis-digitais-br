"""PII redactor tests — adversarial coverage for production LGPD compliance.

Coverage goals:
  - Each PII type: ≥1 positive case (formatted + unformatted variants)
  - False-positive controlled: text that looks PII-shaped but isn't
  - Multi-type queries (compound PII)
  - Ordering invariants (CPF/CNPJ overlap, email vs phone)
  - Edge cases: empty string, whitespace, no PII
  - Audit-log invariants: hash determinism, no PII in summary
"""

from __future__ import annotations

from rag_leis.pii import (
    redact,
    summarize,
    unredact,
)

# ----------------------------------------------------------------------------
# CPF
# ----------------------------------------------------------------------------


def test_cpf_formatted():
    rq = redact("O CPF 123.456.789-00 foi vazado")
    assert "[CPF#1]" in rq.redacted_text
    assert "123.456.789-00" not in rq.redacted_text
    assert "cpf" in rq.pii_types_found


def test_cpf_unformatted():
    rq = redact("CPF 12345678900 do funcionário")
    assert "[CPF#1]" in rq.redacted_text
    assert "12345678900" not in rq.redacted_text


def test_two_cpfs_get_distinct_numbers():
    rq = redact("CPFs 111.111.111-11 e 222.222.222-22")
    assert "[CPF#1]" in rq.redacted_text
    assert "[CPF#2]" in rq.redacted_text
    assert "111.111.111-11" not in rq.redacted_text
    assert "222.222.222-22" not in rq.redacted_text


# ----------------------------------------------------------------------------
# CNPJ
# ----------------------------------------------------------------------------


def test_cnpj_formatted():
    rq = redact("CNPJ 12.345.678/0001-90 da empresa")
    assert "[CNPJ#1]" in rq.redacted_text
    assert "12.345.678/0001-90" not in rq.redacted_text


def test_cnpj_unformatted():
    rq = redact("CNPJ 12345678000190 emitido")
    assert "[CNPJ#1]" in rq.redacted_text
    assert "12345678000190" not in rq.redacted_text


def test_cpf_and_cnpj_distinct_types():
    """11-digit blob is CPF; 14-digit blob is CNPJ. No collision."""
    rq = redact("CPF 11111111111 e CNPJ 12345678000190")
    assert "[CPF#1]" in rq.redacted_text
    assert "[CNPJ#1]" in rq.redacted_text


# ----------------------------------------------------------------------------
# Email
# ----------------------------------------------------------------------------


def test_email_simple():
    rq = redact("Contato joao@empresa.com.br")
    assert "[EMAIL#1]" in rq.redacted_text
    assert "joao@empresa.com.br" not in rq.redacted_text


def test_email_with_plus_alias():
    rq = redact("Notificar maria+spam@example.com")
    assert "[EMAIL#1]" in rq.redacted_text
    assert "maria+spam@example.com" not in rq.redacted_text


def test_email_uppercase():
    rq = redact("MARIA@EXAMPLE.COM")
    assert "[EMAIL#1]" in rq.redacted_text


# ----------------------------------------------------------------------------
# Phone
# ----------------------------------------------------------------------------


def test_phone_mobile_with_ddd():
    rq = redact("Telefone (11) 99999-8888")
    assert "[PHONE#1]" in rq.redacted_text
    assert "(11) 99999-8888" not in rq.redacted_text


def test_phone_landline():
    rq = redact("Tel. (11) 3333-4444")
    assert "[PHONE#1]" in rq.redacted_text


def test_phone_no_parens():
    rq = redact("Liguem 11 99999-8888 amanhã")
    assert "[PHONE#1]" in rq.redacted_text


# ----------------------------------------------------------------------------
# CEP
# ----------------------------------------------------------------------------


def test_cep_with_dash():
    rq = redact("CEP 01310-100 em SP")
    assert "[CEP#1]" in rq.redacted_text
    assert "01310-100" not in rq.redacted_text


# ----------------------------------------------------------------------------
# RG
# ----------------------------------------------------------------------------


def test_rg_formatted():
    rq = redact("RG 12.345.678-9 SSP")
    assert "[RG#1]" in rq.redacted_text


def test_rg_with_x_check_digit():
    """Some RGs use X as check digit."""
    rq = redact("RG 12.345.678-X")
    assert "[RG#1]" in rq.redacted_text


# ----------------------------------------------------------------------------
# Multi-type / compound queries
# ----------------------------------------------------------------------------


def test_compound_pii_query():
    """The canonical production case from the reviewer's critique."""
    rq = redact(
        "Vazaram CPF 123.456.789-00 e email joao@empresa.com do funcionário, "
        "qual o procedimento LGPD?"
    )
    assert "[CPF#1]" in rq.redacted_text
    assert "[EMAIL#1]" in rq.redacted_text
    assert "123.456.789-00" not in rq.redacted_text
    assert "joao@empresa.com" not in rq.redacted_text
    assert rq.pii_types_found == frozenset({"cpf", "email"})
    assert len(rq.matches) == 2


def test_kitchen_sink_all_types():
    """Every PII type in one query — placeholder counters reset per-type."""
    rq = redact(
        "CPF 111.111.111-11, CNPJ 12.345.678/0001-90, "
        "email a@b.com, fone (11) 99999-8888, "
        "CEP 01310-100, RG 12.345.678-9"
    )
    assert "[CPF#1]" in rq.redacted_text
    assert "[CNPJ#1]" in rq.redacted_text
    assert "[EMAIL#1]" in rq.redacted_text
    assert "[PHONE#1]" in rq.redacted_text
    assert "[CEP#1]" in rq.redacted_text
    assert "[RG#1]" in rq.redacted_text
    assert rq.pii_types_found == frozenset({"cpf", "cnpj", "email", "phone", "cep", "rg"})


# ----------------------------------------------------------------------------
# False-positive controlled cases (PII-shaped but NOT PII)
# ----------------------------------------------------------------------------


def test_legal_text_with_article_numbers_not_redacted():
    """Article numbers like 'Art. 5' must not trigger CPF/phone."""
    rq = redact("O Art. 5 da Constituição prevê o art. 154-A do CP")
    assert rq.matches == []
    assert rq.redacted_text == "O Art. 5 da Constituição prevê o art. 154-A do CP"


def test_law_dates_not_redacted_as_phone():
    """Date '14/08/2018' and law number 'Lei 13.709/2018' should not
    redact as phone — they don't match the (DD) prefix pattern."""
    rq = redact("Lei 13.709/2018 publicada em 14/08/2018")
    # Note: "13.709" is 5 digits, not enough for CEP (5+3). Should pass clean.
    # Important assertion: the law citation itself doesn't trigger anything.
    assert "[CPF" not in rq.redacted_text
    assert "[PHONE" not in rq.redacted_text


def test_plain_legal_query_unchanged():
    """A typical eval-set query has no PII; redactor must be no-op."""
    rq = redact("qual a definição de dado pessoal na LGPD?")
    assert rq.matches == []
    assert rq.redacted_text == "qual a definição de dado pessoal na LGPD?"
    assert rq.pii_types_found == frozenset()


# ----------------------------------------------------------------------------
# Edge cases
# ----------------------------------------------------------------------------


def test_empty_string():
    rq = redact("")
    assert rq.redacted_text == ""
    assert rq.matches == []
    assert rq.original_hash  # hash of empty is still defined


def test_whitespace_only():
    rq = redact("   \n  ")
    assert rq.matches == []


def test_hash_is_deterministic():
    """Same input → same hash. Critical for audit log idempotency."""
    a = redact("test CPF 111.111.111-11")
    b = redact("test CPF 111.111.111-11")
    assert a.original_hash == b.original_hash


def test_different_inputs_different_hashes():
    a = redact("CPF 111.111.111-11")
    b = redact("CPF 222.222.222-22")
    assert a.original_hash != b.original_hash


# ----------------------------------------------------------------------------
# unredact() — reverse mapping
# ----------------------------------------------------------------------------


def test_unredact_roundtrip():
    text = "CPF 111.111.111-11 do João"
    rq = redact(text)
    restored = unredact(rq.redacted_text, rq.matches)
    assert restored == text


def test_unredact_handles_lost_placeholders():
    """If the LLM output rephrases the placeholder (e.g., expands [CPF#1]
    into a description), unredact doesn't crash — just returns what
    it can replace."""
    rq = redact("CPF 123.456.789-00 foi vazado")
    # Simulate an LLM that paraphrased away the placeholder
    out = unredact("O dado pessoal mencionado foi indevidamente exposto.", rq.matches)
    # No placeholder in input → no substitutions made → text unchanged
    assert out == "O dado pessoal mencionado foi indevidamente exposto."


# ----------------------------------------------------------------------------
# summarize() — log line, no PII leak
# ----------------------------------------------------------------------------


def test_summarize_no_pii_text_leak():
    """The summary string is intended for logs/observability; it MUST NOT
    contain the original PII tokens."""
    rq = redact("CPF 123.456.789-00 e email joao@x.com")
    summary = summarize(rq)
    assert "123.456.789-00" not in summary
    assert "joao@x.com" not in summary
    # But it should report the counts
    assert "cpf" in summary
    assert "email" in summary
    assert "2 PII matches" in summary


def test_summarize_empty():
    rq = redact("Não há PII aqui, só texto comum sobre LGPD.")
    assert summarize(rq).startswith("no PII")


# ----------------------------------------------------------------------------
# Schema invariants
# ----------------------------------------------------------------------------


def test_match_position_in_original_text():
    """PIIMatch.position is the offset in the ORIGINAL text (pre-redaction)."""
    rq = redact("foo CPF 111.111.111-11 bar")
    assert len(rq.matches) == 1
    m = rq.matches[0]
    assert m.original == "111.111.111-11"
    # The original text "foo CPF " is 8 chars; CPF starts at position 8
    assert m.position == 8


def test_pii_types_found_is_deduplicated():
    """Two CPFs → pii_types_found has one entry, not two."""
    rq = redact("CPFs 111.111.111-11 e 222.222.222-22")
    assert rq.pii_types_found == frozenset({"cpf"})
    assert len(rq.matches) == 2  # but matches preserves both


# ----------------------------------------------------------------------------
# Phase 18.5 — OAB, CRM, processo CNJ, título eleitor
# ----------------------------------------------------------------------------


def test_oab_formatted_with_state():
    rq = redact("O advogado da OAB/SP 123.456 protocolou a peça.")
    assert "[OAB#1]" in rq.redacted_text
    assert "123.456" not in rq.redacted_text
    assert "oab" in rq.pii_types_found


def test_oab_dash_state():
    rq = redact("OAB-RJ 234567 - advogado constituído")
    assert "[OAB#1]" in rq.redacted_text
    assert "234567" not in rq.redacted_text


def test_oab_state_after_number():
    rq = redact("inscrito na OAB nº 123.456/SP")
    assert "[OAB#1]" in rq.redacted_text


def test_oab_no_state_still_matched():
    """State code is legally required but practitioners drop it. The
    regex still matches — under-matching here is worse than over-
    matching (LGPD posture)."""
    rq = redact("OAB 234567 da subseção")
    assert "[OAB#1]" in rq.redacted_text


def test_oab_lowercase_doesnt_match_bare_word():
    """'oab' lowercase is case-insensitive matched, but only when
    followed by ID-shaped digits. Bare 'OAB' word in prose stays."""
    rq = redact("o Conselho da OAB editou a resolução")
    assert "[OAB#" not in rq.redacted_text
    assert "oab" not in rq.pii_types_found


def test_crm_formatted_with_state():
    rq = redact("O médico CRM/SP 12345 atestou.")
    assert "[CRM#1]" in rq.redacted_text
    assert "12345" not in rq.redacted_text
    assert "crm" in rq.pii_types_found


def test_crm_dash_state():
    rq = redact("CRM-MG 67890 emitiu o laudo")
    assert "[CRM#1]" in rq.redacted_text


def test_crm_does_not_overmatch_bare_word():
    """'CRM' in prose without a following ID number stays unredacted."""
    rq = redact("o paciente apresentou o CRM ao recepcionista")
    assert "[CRM#" not in rq.redacted_text


def test_processo_cnj():
    """Unified case number — distinctive 7-2-4-1-2-4 grouping."""
    rq = redact("autos nº 1234567-89.2020.8.26.0001 distribuídos hoje")
    assert "[PROCESSO_CNJ#1]" in rq.redacted_text
    assert "1234567-89.2020.8.26.0001" not in rq.redacted_text
    assert "processo_cnj" in rq.pii_types_found


def test_processo_cnj_does_not_match_partial_format():
    """A 20-digit blob without the dash + dot punctuation is NOT a
    CNJ-format match — we require the specific separators that uniquely
    identify the format. This protects against unrelated long-digit
    strings being mis-redacted."""
    rq = redact("número 12345678920208260001 não é formato CNJ")
    assert "[PROCESSO_CNJ#" not in rq.redacted_text


def test_titulo_eleitor_spaced_format():
    rq = redact("título de eleitor 1234 5678 9012 conferido")
    assert "[TITULO_ELEITOR#1]" in rq.redacted_text
    assert "1234 5678 9012" not in rq.redacted_text
    assert "titulo_eleitor" in rq.pii_types_found


def test_titulo_eleitor_does_not_match_bare_12_digits():
    """The 4-4-4 spaced form is the redaction target; a 12-digit blob
    is too generic (account numbers, dates, etc.) and stays. Documented
    trade-off — see pii.py docstring."""
    rq = redact("código 123456789012 do sistema interno")
    assert "[TITULO_ELEITOR#" not in rq.redacted_text


def test_lawyer_query_multi_pii_phase_18_5():
    """Realistic Phase 14-audit-style query: a lawyer mentions OAB
    + CPF + processo CNJ together. All three must redact independently."""
    rq = redact(
        "Cliente CPF 123.456.789-00, advogado OAB/SP 234.567, autos "
        "1234567-89.2020.8.26.0001."
    )
    assert "[CPF#1]" in rq.redacted_text
    assert "[OAB#1]" in rq.redacted_text
    assert "[PROCESSO_CNJ#1]" in rq.redacted_text
    assert rq.pii_types_found >= {"cpf", "oab", "processo_cnj"}


def test_two_oabs_get_distinct_numbers():
    rq = redact("OAB/SP 123.456 e OAB/RJ 234567 atuam no caso")
    assert "[OAB#1]" in rq.redacted_text
    assert "[OAB#2]" in rq.redacted_text
