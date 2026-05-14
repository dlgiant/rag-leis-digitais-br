# Propostas automáticas (Claude) — gold expansion paráfrase

Pra cada uma das 12 queries não-revisadas (1 + 6-16), propostas seguindo o padrão observado nas suas marcações de [2-5]:

- `core` = chunk responde **diretamente** à pergunta principal
- `supporting` = parágrafo/inciso irmão estrutural que delimita, qualifica ou completa a regra
- não marcado = sub-tópico diferente, sub-listas nominais, leis cruzadas (a menos que paráfrase naturalmente abra cross-doc)

Cada proposta tem 1 linha de razão. Aceite/rejeite/edite — eu atualizo `queries.yaml` baseado no que sobrar.

---

## [1] minha empresa precisa pedir autorização pra mandar e-mail marketing? (MRR 0.333)

Gold atual: `art.7;inc1` + `art.8` (core).

**Propor adicionar como `supporting`** (todos LGPD art.8 paragrafos = forma/ônus do consentimento, mais alternativa contratual):
- `art.8;par1` — consentimento por escrito em cláusula destacada
- `art.8;par2` — ônus da prova com controlador
- `art.8;par3` — vedado vício de consentimento
- `art.8;par4` — finalidades determinadas, autorizações genéricas nulas
- `art.7;inc5` — execução de contrato (alternativa ao consent que a pergunta implícita cobre)

---

## [6] quero saber tudo que uma empresa tem sobre mim, posso pedir? (MRR 0.125)

Gold atual: `art.18;inc2` (core, "acesso aos dados").

**Propor adicionar como `core`** (sub-perguntas igualmente diretas):
- `art.18` — caput "tem direito a obter do controlador, mediante requisição:" (introduz o direito buscado)
- `art.18;inc1` — confirmação da existência de tratamento (parte de "saber tudo")

**Propor adicionar como `supporting`** (mecanismo/forma do exercício):
- `art.18;par3` — requerimento expresso
- `art.18;par5` — sem custos
- `art.18;par8` — pode exercer perante defesa do consumidor
- `art.18;inc7` — info entidades com compartilhamento
- `art.19` — confirmação ou acesso providenciados
- `art.19;par2` — forma do fornecimento
- `art.19;par3` — cópia eletrônica integral

---

## [7] se vazaram meus dados, alguém me avisa? (MRR 0.111)

Gold atual: `art.48` (core, "controlador deverá comunicar à autoridade nacional e ao titular").

**Propor adicionar como `supporting`** (todos detalhes da notificação no mesmo artigo):
- `art.48;par1` — caput da forma da comunicação
- `art.48;par1;inc1` — descrição dos dados afetados
- `art.48;par1;inc2` — info dos titulares envolvidos
- `art.48;par1;inc3` — medidas técnicas usadas
- `art.48;par1;inc4` — riscos relacionados
- `art.48;par1;inc6` — medidas de mitigação
- `art.48;par2` — autoridade pode determinar providências
- `art.48;par2;inc1` — divulgação ampla em meios
- `art.48;par3` — juízo de gravidade

---

## [8] policial pode pedir meus dados pra investigar crime? (MRR 0.500)

Gold atual: `decreto 8771 art.11` + `MCI art.10;par3` (core); `decreto 8771 art.11;par1` + `par2` (supporting).

**Propor adicionar como `supporting`** (definições e limites do mesmo decreto art.11):
- `decreto 8771 art.11;par2;inc1` — filiação (item de "dados cadastrais")
- `decreto 8771 art.11;par2;inc2` — endereço
- `decreto 8771 art.11;par2;inc3` — qualificação pessoal
- `decreto 8771 art.11;par3` — vedados pedidos genéricos/coletivos

---

## [9] alguém me ameaçou online, posso processar? (MRR 0.333)

Gold atual: `CP art.147` (core, ameaça).

**Propor adicionar como `supporting`** (parágrafos do mesmo art.147):
- `art.147;par1` — pena em dobro contra mulher
- `art.147;par2` — somente mediante representação ("posso processar?" → sim, requer rep.)

**NÃO propor**: top-10 trouxe muitos artigos sobre OUTROS crimes via internet (art.146-A intimidação, art.141 calúnia em rede, art.122 homicídio rede, art.147-A perseguição). Cada um é resposta para uma query diferente — manter especificidade.

---

## [10] clonaram meu cartão pela internet, qual artigo se aplica? (MRR 0.000)

Gold atual: `CP art.171` (core, estelionato). Dense não acha art.171 no top-10 — só sub-incisos.

**Propor adicionar como `core`** (artigos paralelos legitimamente aplicáveis a clonagem):
- `CP art.298;par1` — equipara cartão de crédito a documento particular (base pra falsificação documental, frequentemente charge em clonagem)
- `CP art.154-a` — invasão de dispositivo (clonagem na internet pode envolver invasão prévia)

**Propor adicionar como `supporting`**:
- `art.171;par2` — qualificadora servidor fora do território (modalidade da fraude eletrônica)

---

## [11] publicaram fotos íntimas minhas sem autorização, isso é crime? (MRR 0.250)

Gold atual: `CP art.218-c` (core, divulgação de cena de sexo/nudez).

**Propor adicionar como `core`** (artigo paralelo igualmente direto):
- `CP art.216-b` — produzir/fotografar/filmar conteúdo íntimo sem autorização (precede divulgação; pergunta cobre ambos)

**Propor adicionar como `supporting`**:
- `art.216-b;par1` — montagem/inclusão em cena íntima
- `art.218-c;par1` — pena aumentada (vingança, relação afetiva)
- `art.218-c;par2` — não há crime se jornalístico/científico (excludente)

---

## [12] criaram um perfil falso com meu nome nas redes, há crime? (MRR 1.000)

Gold atual: `CP art.307` (core, falsa identidade).

**Propor adicionar como `supporting`** (qualificadora de honra em rede social, frequentemente conexa):
- `CP art.141;par2` — pena em triplo se calúnia/difamação em rede social

**NÃO propor**: art.309 (estrangeiro), art.308 (passaporte alheio), art.146-A (intimidação) — condutas distintas.

---

## [13] tenho direito de saber o que o governo guarda sobre mim? (MRR 0.000)

Gold atual: `CF art.5;inc72` (core, "conceder-se-á habeas-data:" — só o caput-stem do inciso).

**Propor adicionar como `core`** (a alínea-a literalmente responde):
- `CF art.5;inc72;ali-a` — "para assegurar o conhecimento de informações relativas à pessoa do impetrante, constantes de registros... de entidades governamentais"

**Propor adicionar como `supporting`** (mesmo art.5 da CF, direito conexo):
- `CF art.5;inc33` — direito a receber dos órgãos públicos info de interesse particular

**NÃO propor cross-law** (LAI art.7;inc.2, LGPD art.18) — seguindo seu padrão de queries [3-5] que ficou em uma lei só.

---

## [14] podem me processar por escrever opinião na internet? (MRR 0.333)

Gold atual: `CF art.220` (core, manifestação do pensamento).

**Propor adicionar como `supporting`** (parágrafo do mesmo art.220 — vedada censura):
- `CF art.220;par2` — vedada censura política, ideológica, artística

**NÃO propor cross-law**: top-10 tem CP art.142 (excludentes de honra) e MCI art.19 (responsabilidade civil) — relevantes mas seguindo seu padrão fica fora.

---

## [15] minha empresa precisa nomear alguém responsável pelos dados dos clientes? (MRR 0.250)

Gold atual: `art.41` (core, "controlador deverá indicar encarregado").

**Propor adicionar como `supporting`** (todos parágrafos do art.41 + def relacionada):
- `art.41;par1` — identidade do encarregado deve ser pública
- `art.41;par2` — atividades do encarregado (caput)
- `art.41;par2;inc1` — aceitar reclamações
- `art.41;par2;inc2` — comunicações da ANPD
- `art.41;par2;inc3` — orientar funcionários
- `art.41;par2;inc4` — outras atribuições
- `art.41;par3` — autoridade nacional define dispensa
- `art.5;inc8` — definição de "encarregado"

**NÃO propor**: `art.41;par4` (VETADO, sem conteúdo).

---

## [16] se vazaram dados e eu sofri prejuízo, quem responde? (MRR 0.200)

Gold atual: `art.42` + `art.43` (core).

**Propor adicionar como `supporting`** (todos parágrafos do art.42 + artigos vizinhos sobre responsabilidade):
- `art.42;par1` — efetiva indenização
- `art.42;par1;inc1` — operador solidário
- `art.42;par1;inc2` — controladores solidários
- `art.42;par2` — inverter ônus da prova
- `art.42;par3` — ações coletivas
- `art.42;par4` — direito de regresso
- `art.43;inc3` — excludente: culpa exclusiva
- `art.44;par1` — responde quem deixou de adotar medidas de segurança
- `art.45` — responsabilidade nas relações de consumo

---

## Resumo numérico

| query | propostas core | propostas supporting | total novos |
|---|---:|---:|---:|
| [1] e-mail marketing | 0 | 5 | 5 |
| [6] saber tudo | 2 | 7 | 9 |
| [7] vazamento aviso | 0 | 9 | 9 |
| [8] policial dados | 0 | 4 | 4 |
| [9] ameaçou online | 0 | 2 | 2 |
| [10] clonaram cartão | 2 | 1 | 3 |
| [11] fotos íntimas | 1 | 3 | 4 |
| [12] perfil falso | 0 | 1 | 1 |
| [13] habeas data gov | 1 | 1 | 2 |
| [14] opinião internet | 0 | 1 | 1 |
| [15] encarregado | 0 | 8 | 8 |
| [16] vazamento responde | 0 | 9 | 9 |
| **total** | **6** | **51** | **57** |

Plus suas marcações em [2-5]:
- [2] 4 supporting
- [3] 4 supporting
- [4] 8 core
- [5] 3 core

**Grande total proposto**: 18 core + 59 supporting = **77 chunks novos** marcados em 16 queries.

## Próximo passo

Você revisa as propostas (15-20 min — passa pelos 12 queries acima e marca as que aceita/rejeita), eu atualizo `queries.yaml` com base no consenso, re-rodo o eval, e medimos o ganho real em paráfrase MRR.
