# rag-leis-digitais-br

Este RAG indexa direito digital brasileiro usando URN LEX (RFC 9676) como ID
estável de chunk. A hierarquia de chunking segue a LCP-95 (artigo → parágrafo
→ inciso → alínea), o que permite usar citações jurídicas como chave primária
do índice vetorial e fazer verificação de citação por correspondência exata.

## Cobertura atual (2026-05-14)

**Tier 1 — núcleo (13 documentos):** Constituição Federal/1988 (texto compilado
com EC até a corrente), CDC (Lei 8.078/1990), Código Penal (Decreto-Lei
2.848/1940), Lei do Software (9.609/1998), Lei de Direitos Autorais
(9.610/1998), Lei de Acesso à Informação (12.527/2011), Lei Carolina
Dieckmann (12.737/2012), Marco Civil da Internet (12.965/2014), Decreto
8.771/2016 (regulamenta MCI), Lei 9.507/1997 (procedimento do habeas data),
LGPD (13.709/2018), Lei 13.853/2019 (cria a ANPD), Lei 14.155/2021 (crimes
cibernéticos).

**Tier 2 — complementar (3 documentos):** Lei 11.419/2006 (informatização do
processo judicial), Lei 14.063/2020 (assinaturas eletrônicas), Lei 14.129/2021
(Governo Digital).

## Cobertura planejada (não-indexada ainda)

- **Tier 3 — resoluções da ANPD** (Phase 4): Res. CD/ANPD 1/2021, 2/2022,
  4/2023, 15/2024. Necessário para queries operacionais (prazos, dosimetria
  de sanções).
- **Tier 4 — jurisprudência STF/STJ** (Phase 6): Súmulas STJ 227, 403, 479;
  STF Tema 786 (direito ao esquecimento), Tema 987 (MCI 19, pendente).

Roadmap detalhado em `study/post-review-plan.md`.

## Camada de vigência

Acima do parser, `data/vigencia/overlays.yaml` anexa metadados de vigência a
URNs cuja aplicação está ressalvada (sub judice, eficácia limitada por
regulamentação, EC modificadora). Quando o RAG cita uma fonte com overlay,
o gerador é obrigado a inserir um aviso `⚠️ Atenção: ...` na resposta. Cobre
~12 dispositivos hoje (MCI 19/21 sub judice no STF Tema 987, LGPD 52/52§1
eficácia limitada pela ANPD Res. 4/2023, etc.).
