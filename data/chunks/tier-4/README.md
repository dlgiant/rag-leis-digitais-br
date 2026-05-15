# Tier 4 — Jurisprudência (STF/STJ)

Phase 6.1 entrega 7 chunks atômicos de jurisprudência (sem hierarquia LCP-95):
3 súmulas STJ + 4 temas de repercussão geral STF. **Todos manualmente escritos
pelo Claude Code.** Real scrapers contra `portal.stf.jus.br` e `scon.stj.jus.br`
ficam para Phase 6.3 (gated).

## Composição

| URN | Texto | Status | Confiança verbatim |
|---|---|---|---|
| `superior.tribunal.justica:sumula:1999-09-08;227` | Pessoa jurídica e dano moral | vigente | ALTA — texto canônico |
| `superior.tribunal.justica:sumula:2009-10-28;403` | Publicação de imagem com fins econômicos | vigente | ALTA — texto canônico |
| `superior.tribunal.justica:sumula:2012-06-27;479` | Bancos e fraude de terceiros | vigente | ALTA — texto canônico |
| `supremo.tribunal.federal:tema:786` | Direito ao esquecimento | tese-fixada | ALTA — tese verbatim publicada |
| `supremo.tribunal.federal:tema:987` | Constitucionalidade art. 19 MCI | tese-fixada-pendente-transcricao-verbatim | **STUB** — texto descritivo |
| `supremo.tribunal.federal:tema:533` | Sigilo bancário e Receita Federal | tese-fixada-pendente-transcricao-verbatim | **STUB** — texto descritivo |
| `supremo.tribunal.federal:tema:815` | Bloqueio judicial de aplicações | pendente_julgamento | **STUB** — sem tese |

## Por que stubs para Tema 987, 533, 815

Os três temas STF acima entram como **descrição resumida** (`partition: ~ementa`,
não `~tese`) porque transcrever a tese verbatim sem ter o acórdão na frente
seria confabulação — exatamente o problema que resolvemos em Phase 5.1
(Marítaca confabulando sobre PL não promulgado).

Política da Phase 6.1:
- Texto começa com prefixo "STUB — DESCRIÇÃO RESUMIDA, NÃO É A TESE VERBATIM"
- `nav.status = "tese-fixada-pendente-transcricao-verbatim"` ou `"pendente_julgamento"`
- `notes[]` flagam `PENDENTE_REVISAO_JURIDICA` para o D7 lawyer
- `nav.rank_motivo` documenta que o rank URN aplicável é 3, mas o conteúdo
  é resumo curatorial — Phase 6.5 hierarchy_warning deve refletir isso

## Próximos passos (D7 lawyer-review-checklist.md item 5)

Quando o consultor jurídico for contratado:
1. Substituir os 3 stubs por tese verbatim copiada do acórdão STF publicado
2. Atualizar `nav.status` para `tese-fixada` (sem o sufixo `-pendente-...`)
3. Remover as notes `PENDENTE_REVISAO_JURIDICA`
4. Para Tema 815: atualizar quando houver tese (acompanhar `portal.stf.jus.br`)

## Schema dos chunks

Cada linha do JSONL é um chunk:
```json
{
  "document_urn": "urn:lex:br:<tribunal>:<tipo>:<id>",
  "partition": "tese|enunciado|ementa",
  "kind": "jurisprudencia",
  "label": "Curto, exibível ao usuário",
  "text": "Verbatim ou stub descritivo prefixado",
  "parent_partition": null,
  "nav": {
    "tribunal": "STF|STJ",
    "tipo": "Súmula|Súmula Vinculante|Tema de Repercussão Geral",
    "numero": "...",
    "status": "vigente|tese-fixada|pendente_julgamento|...",
    "referencia": "URL do tribunal"
  },
  "notes": [],
  "is_revoked": false,
  "urn": "<document_urn>~<partition>"
}
```

`nav` é flexível propositalmente — adiciona `processo_paradigma`, `relator`,
`data_julgamento`, etc. conforme o tipo. O renderer no answer payload itera
os campos disponíveis.

## Provenance fields

Cada chunk traz:
- `source`: `"claude-code-2026-05-15"` (fonte humana + data, igual a Phase 4.3.a)
- `ingestion_method`: `"manual-transcription-v0"` ou `"manual-stub-v0"`
- `ingestion_provenance`: descrição em prosa do método

Phase 6.3 (real scrapers) trocará para `"stf-scraper-v1"` /
`"scon-stj-scraper-v1"` com SHA-256 do HTML/PDF capturado.
