# Gold review — qtype=parafrase (16 queries)

Model: `voyage-3-large` / mode: `label+nav+caput+text` / top-10 per query.

**Como usar este worksheet:**

Pra cada query, leia o `current gold` e os `top-K retrieved`. Se um chunk
retornado **NÃO** está no gold mas é uma resposta semanticamente válida
(ou parcial), mude o checkbox correspondente:

- `[ ] add as core` → trocar pra `[x] add as core` se o chunk responde a query principal
- `[ ] add as supporting` → marcar se é contexto/regra adjacente que ajuda
- Deixar em branco se não-relevante

Depois eu (ou você) atualiza `eval/queries.yaml` baseado nas marcações.

---

## [1] minha empresa precisa pedir autorização pra mandar e-mail marketing?

- **MRR@10 atual**: 0.500  |  notes: LGPD art. 7 I (consent base legal) + art. 8 (forma) + CDC art. 39 III (envio sem solicitação prévia = prática abusiva). Supporting: CDC art. 39 caput; LGPD art. 7 V (alternativa contratual); LGPD art. 8 §§ 1-4 (forma/ônus/vício/finalidade).

**Current gold:**

- `core` → `urn:lex:br:federal:lei:1990-09-11;8078~art39;inc3` — enviar ou entregar ao consumidor, sem solicitação prévia, qualquer produto, ou fornecer qualquer serviço;
- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1` — mediante o fornecimento de consentimento pelo titular;
- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art8` — O consentimento previsto no inciso I do art. 7º desta Lei deverá ser fornecido por escrito ou por outro meio que demonstre a manifestação de vontade …
- `supporting` → `urn:lex:br:federal:lei:1990-09-11;8078~art39` — É vedado ao fornecedor de produtos ou serviços, dentre outras práticas abusivas:
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art7;inc5` — quando necessário para a execução de contrato ou de procedimentos preliminares relacionados a contrato do qual seja parte o titular, a pedido do titu…
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art8;par1` — Caso o consentimento seja fornecido por escrito, esse deverá constar de cláusula destacada das demais cláusulas contratuais.
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art8;par2` — Cabe ao controlador o ônus da prova de que o consentimento foi obtido em conformidade com o disposto nesta Lei.
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art8;par3` — É vedado o tratamento de dados pessoais mediante vício de consentimento.
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art8;par4` — O consentimento deverá referir-se a finalidades determinadas, e as autorizações genéricas para o tratamento de dados pessoais serão nulas.

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.5679)    
- URN: `urn:lex:br:federal:decreto:2016-05-11;8771~art11;par1`
- nav: III - DA PROTEÇÃO AOS REGISTROS, AOS DADOS PESSOAIS E ÀS COMUNICAÇÕES PRIVADAS > I - Da requisição de dados cadastrais
- text: O provedor que não coletar dados cadastrais deverá informar tal fato à autoridade solicitante, ficando desobrigado de fornecer tais dados.
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 2  (sim=0.5669)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art8;par4`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > I Dos Requisitos para o Tratamento de Dados Pessoais
- text: O consentimento deverá referir-se a finalidades determinadas, e as autorizações genéricas para o tratamento de dados pessoais serão nulas.

### Rank 3  (sim=0.5652)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > I Dos Requisitos para o Tratamento de Dados Pessoais
- text: mediante o fornecimento de consentimento pelo titular;

### Rank 4  (sim=0.5591)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art8;par2`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > I Dos Requisitos para o Tratamento de Dados Pessoais
- text: Cabe ao controlador o ônus da prova de que o consentimento foi obtido em conformidade com o disposto nesta Lei.

### Rank 5  (sim=0.5586)    
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art10;inc1`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > I Dos Requisitos para o Tratamento de Dados Pessoais
- text: apoio e promoção de atividades do controlador; e
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 6  (sim=0.5575)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art7;inc5`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > I Dos Requisitos para o Tratamento de Dados Pessoais
- text: quando necessário para a execução de contrato ou de procedimentos preliminares relacionados a contrato do qual seja parte o titular, a pedido do titular dos dados;

### Rank 7  (sim=0.5547)    
- URN: `urn:lex:br:federal:decreto:2016-05-11;8771~art11`
- nav: III - DA PROTEÇÃO AOS REGISTROS, AOS DADOS PESSOAIS E ÀS COMUNICAÇÕES PRIVADAS > I - Da requisição de dados cadastrais
- text: As autoridades administrativas a que se refere o art. 10, § 3º da Lei nº 12.965, de 2014 , indicarão o fundamento legal de competência expressa para o acesso e a motivação para o pedido de acesso aos dados cadastrais.
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 8  (sim=0.5525)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art8;par1`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > I Dos Requisitos para o Tratamento de Dados Pessoais
- text: Caso o consentimento seja fornecido por escrito, esse deverá constar de cláusula destacada das demais cláusulas contratuais.

### Rank 9  (sim=0.5518)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art8`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > I Dos Requisitos para o Tratamento de Dados Pessoais
- text: O consentimento previsto no inciso I do art. 7º desta Lei deverá ser fornecido por escrito ou por outro meio que demonstre a manifestação de vontade do titular.

### Rank 10  (sim=0.5508)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art8;par3`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > I Dos Requisitos para o Tratamento de Dados Pessoais
- text: É vedado o tratamento de dados pessoais mediante vício de consentimento.

---

## [2] fui invadido no celular sem permissão, isso é crime?

- **MRR@10 atual**: 1.000  |  notes: CP art. 154-A (invasão de dispositivo). Supporting: §§ 1-3, 5 (modalidades, qualificadoras, condutas conexas).

**Current gold:**

- `core` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a` — Invadir dispositivo informático de uso alheio, conectado ou não à rede de computadores, com o fim de obter, adulterar ou destruir dados ou informaçõe…
- `supporting` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par1` — o Na mesma pena incorre quem produz, oferece, distribui, vende ou difunde dispositivo ou programa de computador com o intuito de permitir a prática d…
- `supporting` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par2` — Aumenta-se a pena de 1/3 (um terço) a 2/3 (dois terços) se da invasão resulta prejuízo econômico.
- `supporting` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par3` — o Se da invasão resultar a obtenção de conteúdo de comunicações eletrônicas privadas, segredos comerciais ou industriais, informações sigilosas, assi…
- `supporting` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par5` — o Aumenta-se a pena de um terço à metade se o crime for praticado contra: Vigência

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.6755)  ★ core
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: Invadir dispositivo informático de uso alheio, conectado ou não à rede de computadores, com o fim de obter, adulterar ou destruir dados ou informações sem autorização expressa ou tácita do usuário do dispositivo ou de i…

### Rank 2  (sim=0.6742)  ◐ supporting
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par3`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: o Se da invasão resultar a obtenção de conteúdo de comunicações eletrônicas privadas, segredos comerciais ou industriais, informações sigilosas, assim definidas em lei, ou o controle remoto não autorizado do dispositivo…

### Rank 3  (sim=0.6573)  ◐ supporting
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par5`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: o Aumenta-se a pena de um terço à metade se o crime for praticado contra: Vigência

### Rank 4  (sim=0.6540)  ◐ supporting
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par1`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: o Na mesma pena incorre quem produz, oferece, distribui, vende ou difunde dispositivo ou programa de computador com o intuito de permitir a prática da conduta definida no caput. Vigência

### Rank 5  (sim=0.6536)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par5;inc2`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: Presidente do Supremo Tribunal Federal; Vigência
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 6  (sim=0.6479)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par5;inc1`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: Presidente da República, governadores e prefeitos; Vigência
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 7  (sim=0.6460)  ◐ supporting
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par2`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: Aumenta-se a pena de 1/3 (um terço) a 2/3 (dois terços) se da invasão resulta prejuízo econômico.

### Rank 8  (sim=0.6439)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par5;inc4`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: dirigente máximo da administração direta e indireta federal, estadual, municipal ou do Distrito Federal. Vigência
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 9  (sim=0.6358)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par5;inc3`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: Presidente da Câmara dos Deputados, do Senado Federal, de Assembleia Legislativa de Estado, da Câmara Legislativa do Distrito Federal ou de Câmara Municipal; ou Vigência
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 10  (sim=0.6349)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par4`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: o Na hipótese do § 3o, aumenta-se a pena de um a dois terços se houver divulgação, comercialização ou transmissão a terceiro, a qualquer título, dos dados ou informações obtidos. Vigência
- `[ ] add as core`
- `[ ] add as supporting`

---

## [3] posso fazer uma cópia de backup de um programa que comprei?

- **MRR@10 atual**: 1.000  |  notes: Lei do Software art. 6 I (cópia de salvaguarda). Supporting: art. 6 caput (não-ofensa); inc IV (integração — outra hipótese lícita); art. 2 § 5 (direito exclusivo — delimita); art. 12 § 1 (penalidade reprodução comercial — contraste).

**Current gold:**

- `core` → `urn:lex:br:federal:lei:1998-02-19;9609~art6;inc1` — a reprodução, em um só exemplar, de cópia legitimamente adquirida, desde que se destine à cópia de salvaguarda ou armazenamento eletrônico, hipótese …
- `supporting` → `urn:lex:br:federal:lei:1998-02-19;9609~art12;par1` — Se a violação consistir na reprodução, por qualquer meio, de programa de computador, no todo ou em parte, para fins de comércio, sem autorização expr…
- `supporting` → `urn:lex:br:federal:lei:1998-02-19;9609~art2;par5` — Inclui-se dentre os direitos assegurados por esta Lei e pela legislação de direitos autorais e conexos vigentes no País aquele direito exclusivo de a…
- `supporting` → `urn:lex:br:federal:lei:1998-02-19;9609~art6` — Não constituem ofensa aos direitos do titular de programa de computador:
- `supporting` → `urn:lex:br:federal:lei:1998-02-19;9609~art6;inc4` — a integração de um programa, mantendo-se suas características essenciais, a um sistema aplicativo ou operacional, tecnicamente indispensável às neces…

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.7161)  ★ core
- URN: `urn:lex:br:federal:lei:1998-02-19;9609~art6;inc1`
- nav: II - DA PROTEÇÃO AOS DIREITOS DE AUTOR E DO REGISTRO
- text: a reprodução, em um só exemplar, de cópia legitimamente adquirida, desde que se destine à cópia de salvaguarda ou armazenamento eletrônico, hipótese em que o exemplar original servirá de salvaguarda;

### Rank 2  (sim=0.6184)  ◐ supporting
- URN: `urn:lex:br:federal:lei:1998-02-19;9609~art2;par5`
- nav: II - DA PROTEÇÃO AOS DIREITOS DE AUTOR E DO REGISTRO
- text: Inclui-se dentre os direitos assegurados por esta Lei e pela legislação de direitos autorais e conexos vigentes no País aquele direito exclusivo de autorizar ou proibir o aluguel comercial, não sendo esse direito exaurí…

### Rank 3  (sim=0.6017)  ◐ supporting
- URN: `urn:lex:br:federal:lei:1998-02-19;9609~art6;inc4`
- nav: II - DA PROTEÇÃO AOS DIREITOS DE AUTOR E DO REGISTRO
- text: a integração de um programa, mantendo-se suas características essenciais, a um sistema aplicativo ou operacional, tecnicamente indispensável às necessidades do usuário, desde que para o uso exclusivo de quem a promoveu.

### Rank 4  (sim=0.5995)  ◐ supporting
- URN: `urn:lex:br:federal:lei:1998-02-19;9609~art6`
- nav: II - DA PROTEÇÃO AOS DIREITOS DE AUTOR E DO REGISTRO
- text: Não constituem ofensa aos direitos do titular de programa de computador:

### Rank 5  (sim=0.5985)  ◐ supporting
- URN: `urn:lex:br:federal:lei:1998-02-19;9609~art12;par1`
- nav: V - DAS INFRAÇÕES E DAS PENALIDADES
- text: Se a violação consistir na reprodução, por qualquer meio, de programa de computador, no todo ou em parte, para fins de comércio, sem autorização expressa do autor ou de quem o represente:

### Rank 6  (sim=0.5929)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art184;par4`
- nav: ESPECIAL > III DOS CRIMES CONTRA A PROPRIEDADE IMATERIAL > I DOS CRIMES CONTRA A PROPRIEDADE INTELECTUAL - Violação de direito autoral
- text: o O disposto nos §§ 1o, 2o e 3o não se aplica quando se tratar de exceção ou limitação ao direito de autor ou os que lhe são conexos, em conformidade com o previsto na Lei nº 9.610, de 19 de fevereiro de 1998, nem a cóp…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 7  (sim=0.5874)    
- URN: `urn:lex:br:federal:lei:1998-02-19;9609~art9;par1`
- nav: IV - DOS CONTRATOS DE LICENÇA DE USO, DE COMERCIALIZAÇÃO
- text: Na hipótese de eventual inexistência do contrato referido no caput deste artigo, o documento fiscal relativo à aquisição ou licenciamento de cópia servirá para comprovação da regularidade do seu uso.
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 8  (sim=0.5865)    
- URN: `urn:lex:br:federal:lei:1998-02-19;9609~art5`
- nav: II - DA PROTEÇÃO AOS DIREITOS DE AUTOR E DO REGISTRO
- text: Os direitos sobre as derivações autorizadas pelo titular dos direitos de programa de computador, inclusive sua exploração econômica, pertencerão à pessoa autorizada que as fizer, salvo estipulação contratual em contrári…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 9  (sim=0.5840)    
- URN: `urn:lex:br:federal:lei:1998-02-19;9609~art2;par6`
- nav: II - DA PROTEÇÃO AOS DIREITOS DE AUTOR E DO REGISTRO
- text: O disposto no parágrafo anterior não se aplica aos casos em que o programa em si não seja objeto essencial do aluguel.
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 10  (sim=0.5785)    
- URN: `urn:lex:br:federal:lei:1998-02-19;9609~art6;inc2`
- nav: II - DA PROTEÇÃO AOS DIREITOS DE AUTOR E DO REGISTRO
- text: a citação parcial do programa, para fins didáticos, desde que identificados o programa e o titular dos direitos respectivos;
- `[ ] add as core`
- `[ ] add as supporting`

---

## [4] posso reproduzir um trecho de livro para citar numa aula?

- **MRR@10 atual**: 1.000  |  notes: DA art. 46 — limitações ao direito autoral. Múltiplos incisos respondem a uso didático/citação (inc III canônico, mas inc I/II/IV/VI/VII/VIII também aplicáveis). art. 29 VIII a (representação/declamação) inclusive.

**Current gold:**

- `core` → `urn:lex:br:federal:lei:1998-02-19;9610~art29;inc8;ali-a` — representação, recitação ou declamação;
- `core` → `urn:lex:br:federal:lei:1998-02-19;9610~art46` — Não constitui ofensa aos direitos autorais:
- `core` → `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc1` — a reprodução:
- `core` → `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc2` — a reprodução, em um só exemplar de pequenos trechos, para uso privado do copista, desde que feita por este, sem intuito de lucro;
- `core` → `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc3` — a citação em livros, jornais, revistas ou qualquer outro meio de comunicação, de passagens de qualquer obra, para fins de estudo, crítica ou polêmica…
- `core` → `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc4` — o apanhado de lições em estabelecimentos de ensino por aqueles a quem elas se dirigem, vedada sua publicação, integral ou parcial, sem autorização pr…
- `core` → `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc6` — a representação teatral e a execução musical, quando realizadas no recesso familiar ou, para fins exclusivamente didáticos, nos estabelecimentos de e…
- `core` → `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc7` — a utilização de obras literárias, artísticas ou científicas para produzir prova judiciária ou administrativa;
- `core` → `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc8` — a reprodução, em quaisquer obras, de pequenos trechos de obras preexistentes, de qualquer natureza, ou de obra integral, quando de artes plásticas, s…

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.7360)  ★ core
- URN: `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc2`
- nav: III - Dos Direitos do Autor > IV - Das Limitações aos Direitos Autorais
- text: a reprodução, em um só exemplar de pequenos trechos, para uso privado do copista, desde que feita por este, sem intuito de lucro;

### Rank 2  (sim=0.7204)  ★ core
- URN: `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc3`
- nav: III - Dos Direitos do Autor > IV - Das Limitações aos Direitos Autorais
- text: a citação em livros, jornais, revistas ou qualquer outro meio de comunicação, de passagens de qualquer obra, para fins de estudo, crítica ou polêmica, na medida justificada para o fim a atingir, indicando-se o nome do a…

### Rank 3  (sim=0.7195)  ★ core
- URN: `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc4`
- nav: III - Dos Direitos do Autor > IV - Das Limitações aos Direitos Autorais
- text: o apanhado de lições em estabelecimentos de ensino por aqueles a quem elas se dirigem, vedada sua publicação, integral ou parcial, sem autorização prévia e expressa de quem as ministrou;

### Rank 4  (sim=0.7067)  ★ core
- URN: `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc8`
- nav: III - Dos Direitos do Autor > IV - Das Limitações aos Direitos Autorais
- text: a reprodução, em quaisquer obras, de pequenos trechos de obras preexistentes, de qualquer natureza, ou de obra integral, quando de artes plásticas, sempre que a reprodução em si não seja o objetivo principal da obra nov…

### Rank 5  (sim=0.6960)  ★ core
- URN: `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc1`
- nav: III - Dos Direitos do Autor > IV - Das Limitações aos Direitos Autorais
- text: a reprodução:

### Rank 6  (sim=0.6936)    
- URN: `urn:lex:br:federal:lei:1998-02-19;9609~art6;inc2`
- nav: II - DA PROTEÇÃO AOS DIREITOS DE AUTOR E DO REGISTRO
- text: a citação parcial do programa, para fins didáticos, desde que identificados o programa e o titular dos direitos respectivos;
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 7  (sim=0.6922)  ★ core
- URN: `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc7`
- nav: III - Dos Direitos do Autor > IV - Das Limitações aos Direitos Autorais
- text: a utilização de obras literárias, artísticas ou científicas para produzir prova judiciária ou administrativa;

### Rank 8  (sim=0.6820)  ★ core
- URN: `urn:lex:br:federal:lei:1998-02-19;9610~art29;inc8;ali-a`
- nav: III - Dos Direitos do Autor > III - Dos Direitos Patrimoniais do Autor e de sua Duração
- text: representação, recitação ou declamação;

### Rank 9  (sim=0.6758)  ★ core
- URN: `urn:lex:br:federal:lei:1998-02-19;9610~art46`
- nav: III - Dos Direitos do Autor > IV - Das Limitações aos Direitos Autorais
- text: Não constitui ofensa aos direitos autorais:

### Rank 10  (sim=0.6731)  ★ core
- URN: `urn:lex:br:federal:lei:1998-02-19;9610~art46;inc6`
- nav: III - Dos Direitos do Autor > IV - Das Limitações aos Direitos Autorais
- text: a representação teatral e a execução musical, quando realizadas no recesso familiar ou, para fins exclusivamente didáticos, nos estabelecimentos de ensino, não havendo em qualquer caso intuito de lucro;

---

## [5] a empresa pode usar dados de uma criança sem dizer pros pais?

- **MRR@10 atual**: 1.000  |  notes: LGPD art. 14 caput (proteção de crianças/adolescentes) + § 1 (consentimento dos pais) + § 3 (sem consent quando p/ contatar pais) + § 4 (não condicionar participação) + § 5 (esforços p/ verificar consent dos pais).

**Current gold:**

- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art14` — O tratamento de dados pessoais de crianças e de adolescentes deverá ser realizado em seu melhor interesse, nos termos deste artigo e da legislação pe…
- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art14;par1` — O tratamento de dados pessoais de crianças deverá ser realizado com o consentimento específico e em destaque dado por pelo menos um dos pais ou pelo …
- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art14;par3` — Poderão ser coletados dados pessoais de crianças sem o consentimento a que se refere o § 1º deste artigo quando a coleta for necessária para contatar…
- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art14;par4` — Os controladores não deverão condicionar a participação dos titulares de que trata o § 1º deste artigo em jogos, aplicações de internet ou outras ati…
- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art14;par5` — O controlador deve realizar todos os esforços razoáveis para verificar que o consentimento a que se refere o § 1º deste artigo foi dado pelo responsá…

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.6843)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art14;par3`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > III Do Tratamento de Dados Pessoais de Crianças e de Adolescentes
- text: Poderão ser coletados dados pessoais de crianças sem o consentimento a que se refere o § 1º deste artigo quando a coleta for necessária para contatar os pais ou o responsável legal, utilizados uma única vez e sem armaze…

### Rank 2  (sim=0.6566)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art14;par1`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > III Do Tratamento de Dados Pessoais de Crianças e de Adolescentes
- text: O tratamento de dados pessoais de crianças deverá ser realizado com o consentimento específico e em destaque dado por pelo menos um dos pais ou pelo responsável legal.

### Rank 3  (sim=0.6461)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art14;par5`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > III Do Tratamento de Dados Pessoais de Crianças e de Adolescentes
- text: O controlador deve realizar todos os esforços razoáveis para verificar que o consentimento a que se refere o § 1º deste artigo foi dado pelo responsável pela criança, consideradas as tecnologias disponíveis.

### Rank 4  (sim=0.6375)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art14;par4`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > III Do Tratamento de Dados Pessoais de Crianças e de Adolescentes
- text: Os controladores não deverão condicionar a participação dos titulares de que trata o § 1º deste artigo em jogos, aplicações de internet ou outras atividades ao fornecimento de informações pessoais além das estritamente …

### Rank 5  (sim=0.6365)    
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art14;par6`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > III Do Tratamento de Dados Pessoais de Crianças e de Adolescentes
- text: As informações sobre o tratamento de dados referidas neste artigo deverão ser fornecidas de maneira simples, clara e acessível, consideradas as características físico-motoras, perceptivas, sensoriais, intelectuais e men…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 6  (sim=0.6356)    
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art14;par2`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > III Do Tratamento de Dados Pessoais de Crianças e de Adolescentes
- text: No tratamento de dados de que trata o § 1º deste artigo, os controladores deverão manter pública a informação sobre os tipos de dados coletados, a forma de sua utilização e os procedimentos para o exercício dos direitos…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 7  (sim=0.6263)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art14`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > III Do Tratamento de Dados Pessoais de Crianças e de Adolescentes
- text: O tratamento de dados pessoais de crianças e de adolescentes deverá ser realizado em seu melhor interesse, nos termos deste artigo e da legislação pertinente.

### Rank 8  (sim=0.5822)    
- URN: `urn:lex:br:federal:lei:2014-04-23;12965~art29`
- nav: V DISPOSIÇÕES FINAIS
- text: O usuário terá a opção de livre escolha na utilização de programa de computador em seu terminal para exercício do controle parental de conteúdo entendido por ele como impróprio a seus filhos menores, desde que respeitad…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 9  (sim=0.5776)    
- URN: `urn:lex:br:federal:lei:2014-04-23;12965~art29;par1`
- nav: V DISPOSIÇÕES FINAIS
- text: Cabe ao poder público, em conjunto com os provedores de conexão e de aplicações de internet e a sociedade civil, promover a educação e fornecer informações sobre o uso dos programas de computador previstos no caput, bem…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 10  (sim=0.5539)    
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art7;par6`
- nav: II DO TRATAMENTO DE DADOS PESSOAIS > I Dos Requisitos para o Tratamento de Dados Pessoais
- text: A eventual dispensa da exigência do consentimento não desobriga os agentes de tratamento das demais obrigações previstas nesta Lei, especialmente da observância dos princípios gerais e da garantia dos direitos do titula…
- `[ ] add as core`
- `[ ] add as supporting`

---

## [6] quero saber tudo que uma empresa tem sobre mim, posso pedir?

- **MRR@10 atual**: 1.000  |  notes: LGPD art. 18 + inc I (confirmação) + inc II (acesso) + CDC art. 43 (acesso direto a cadastros/registros sobre o consumidor). Supporting: §§ procedurais do art. 18; art. 19 (forma do fornecimento); CDC art. 43 § 4 (bancos de dados como entidades de caráter público).

**Current gold:**

- `core` → `urn:lex:br:federal:lei:1990-09-11;8078~art43` — O consumidor, sem prejuízo do disposto no art. 86, terá acesso às informações existentes em cadastros, fichas, registros e dados pessoais e de consum…
- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art18` — O titular dos dados pessoais tem direito a obter do controlador, em relação aos dados do titular por ele tratados, a qualquer momento e mediante requ…
- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art18;inc1` — confirmação da existência de tratamento;
- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art18;inc2` — acesso aos dados;
- `supporting` → `urn:lex:br:federal:lei:1990-09-11;8078~art43;par4` — Os bancos de dados e cadastros relativos a consumidores, os serviços de proteção ao crédito e congêneres são considerados entidades de caráter públic…
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art18;inc7` — informação das entidades públicas e privadas com as quais o controlador realizou uso compartilhado de dados;
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art18;par3` — Os direitos previstos neste artigo serão exercidos mediante requerimento expresso do titular ou de representante legalmente constituído, a agente de …
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art18;par5` — O requerimento referido no § 3º deste artigo será atendido sem custos para o titular, nos prazos e nos termos previstos em regulamento.
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art18;par8` — O direito a que se refere o § 1º deste artigo também poderá ser exercido perante os organismos de defesa do consumidor.
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art19` — A confirmação de existência ou o acesso a dados pessoais serão providenciados, mediante requisição do titular:
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art19;par2` — As informações e os dados poderão ser fornecidos, a critério do titular:
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art19;par3` — Quando o tratamento tiver origem no consentimento do titular ou em contrato, o titular poderá solicitar cópia eletrônica integral de seus dados pesso…

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.6657)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art18;par8`
- nav: III DOS DIREITOS DO TITULAR
- text: O direito a que se refere o § 1º deste artigo também poderá ser exercido perante os organismos de defesa do consumidor.

### Rank 2  (sim=0.6612)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art18`
- nav: III DOS DIREITOS DO TITULAR
- text: O titular dos dados pessoais tem direito a obter do controlador, em relação aos dados do titular por ele tratados, a qualquer momento e mediante requisição:

### Rank 3  (sim=0.6612)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art18;inc7`
- nav: III DOS DIREITOS DO TITULAR
- text: informação das entidades públicas e privadas com as quais o controlador realizou uso compartilhado de dados;

### Rank 4  (sim=0.6528)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art18;par5`
- nav: III DOS DIREITOS DO TITULAR
- text: O requerimento referido no § 3º deste artigo será atendido sem custos para o titular, nos prazos e nos termos previstos em regulamento.

### Rank 5  (sim=0.6527)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art18;inc1`
- nav: III DOS DIREITOS DO TITULAR
- text: confirmação da existência de tratamento;

### Rank 6  (sim=0.6493)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art19;par2`
- nav: III DOS DIREITOS DO TITULAR
- text: As informações e os dados poderão ser fornecidos, a critério do titular:

### Rank 7  (sim=0.6479)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art19;par3`
- nav: III DOS DIREITOS DO TITULAR
- text: Quando o tratamento tiver origem no consentimento do titular ou em contrato, o titular poderá solicitar cópia eletrônica integral de seus dados pessoais, observados os segredos comercial e industrial, nos termos de regu…

### Rank 8  (sim=0.6455)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art18;inc2`
- nav: III DOS DIREITOS DO TITULAR
- text: acesso aos dados;

### Rank 9  (sim=0.6450)    
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art19;inc2`
- nav: III DOS DIREITOS DO TITULAR
- text: por meio de declaração clara e completa, que indique a origem dos dados, a inexistência de registro, os critérios utilizados e a finalidade do tratamento, observados os segredos comercial e industrial, fornecida no praz…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 10  (sim=0.6429)  ◐ supporting
- URN: `urn:lex:br:federal:lei:1990-09-11;8078~art43;par4`
- nav: I Dos Direitos do Consumidor > V Das Práticas Comerciais > VI Dos Bancos de Dados e Cadastros de Consumidores
- text: Os bancos de dados e cadastros relativos a consumidores, os serviços de proteção ao crédito e congêneres são considerados entidades de caráter público.

---

## [7] se vazaram meus dados, alguém me avisa?

- **MRR@10 atual**: 1.000  |  notes: LGPD art. 48 (comunicação de incidente). Supporting: § 1 (caput dos detalhes da notificação) + incs I-IV/VI (conteúdo); § 2 e § 2 I (providências da autoridade); § 3 (juízo de gravidade).

**Current gold:**

- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art48` — O controlador deverá comunicar à autoridade nacional e ao titular a ocorrência de incidente de segurança que possa acarretar risco ou dano relevante …
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art48;par1` — A comunicação será feita em prazo razoável, conforme definido pela autoridade nacional, e deverá mencionar, no mínimo:
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art48;par1;inc1` — a descrição da natureza dos dados pessoais afetados;
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art48;par1;inc2` — as informações sobre os titulares envolvidos;
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art48;par1;inc3` — a indicação das medidas técnicas e de segurança utilizadas para a proteção dos dados, observados os segredos comercial e industrial;
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art48;par1;inc4` — os riscos relacionados ao incidente;
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art48;par1;inc6` — as medidas que foram ou que serão adotadas para reverter ou mitigar os efeitos do prejuízo.
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art48;par2` — A autoridade nacional verificará a gravidade do incidente e poderá, caso necessário para a salvaguarda dos direitos dos titulares, determinar ao cont…
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art48;par2;inc1` — ampla divulgação do fato em meios de comunicação; e
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art48;par3` — No juízo de gravidade do incidente, será avaliada eventual comprovação de que foram adotadas medidas técnicas adequadas que tornem os dados pessoais …

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.5981)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art48;par1;inc1`
- nav: VII DA SEGURANÇA E DAS BOAS PRÁTICAS > I Da Segurança e do Sigilo de Dados
- text: a descrição da natureza dos dados pessoais afetados;

### Rank 2  (sim=0.5967)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art48;par2;inc1`
- nav: VII DA SEGURANÇA E DAS BOAS PRÁTICAS > I Da Segurança e do Sigilo de Dados
- text: ampla divulgação do fato em meios de comunicação; e

### Rank 3  (sim=0.5916)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art48;par3`
- nav: VII DA SEGURANÇA E DAS BOAS PRÁTICAS > I Da Segurança e do Sigilo de Dados
- text: No juízo de gravidade do incidente, será avaliada eventual comprovação de que foram adotadas medidas técnicas adequadas que tornem os dados pessoais afetados ininteligíveis, no âmbito e nos limites técnicos de seus serv…

### Rank 4  (sim=0.5839)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art48;par1;inc6`
- nav: VII DA SEGURANÇA E DAS BOAS PRÁTICAS > I Da Segurança e do Sigilo de Dados
- text: as medidas que foram ou que serão adotadas para reverter ou mitigar os efeitos do prejuízo.

### Rank 5  (sim=0.5838)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art48;par1;inc2`
- nav: VII DA SEGURANÇA E DAS BOAS PRÁTICAS > I Da Segurança e do Sigilo de Dados
- text: as informações sobre os titulares envolvidos;

### Rank 6  (sim=0.5828)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art48;par2`
- nav: VII DA SEGURANÇA E DAS BOAS PRÁTICAS > I Da Segurança e do Sigilo de Dados
- text: A autoridade nacional verificará a gravidade do incidente e poderá, caso necessário para a salvaguarda dos direitos dos titulares, determinar ao controlador a adoção de providências, tais como:

### Rank 7  (sim=0.5811)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art48;par1`
- nav: VII DA SEGURANÇA E DAS BOAS PRÁTICAS > I Da Segurança e do Sigilo de Dados
- text: A comunicação será feita em prazo razoável, conforme definido pela autoridade nacional, e deverá mencionar, no mínimo:

### Rank 8  (sim=0.5809)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art48;par1;inc3`
- nav: VII DA SEGURANÇA E DAS BOAS PRÁTICAS > I Da Segurança e do Sigilo de Dados
- text: a indicação das medidas técnicas e de segurança utilizadas para a proteção dos dados, observados os segredos comercial e industrial;

### Rank 9  (sim=0.5788)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art48`
- nav: VII DA SEGURANÇA E DAS BOAS PRÁTICAS > I Da Segurança e do Sigilo de Dados
- text: O controlador deverá comunicar à autoridade nacional e ao titular a ocorrência de incidente de segurança que possa acarretar risco ou dano relevante aos titulares.

### Rank 10  (sim=0.5778)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art48;par1;inc4`
- nav: VII DA SEGURANÇA E DAS BOAS PRÁTICAS > I Da Segurança e do Sigilo de Dados
- text: os riscos relacionados ao incidente;

---

## [8] policial pode pedir meus dados pra investigar crime?

- **MRR@10 atual**: 1.000  |  notes: MCI art. 10 § 3 (autoridade administrativa requisita dados cadastrais) + Decreto 8771 art. 11 (procedimento). Supporting: § 1 (obrigação info), § 2 + incs I-III (definição de dados cadastrais: filiação, endereço, qualificação), § 3 (vedados pedidos genéricos).

**Current gold:**

- `core` → `urn:lex:br:federal:decreto:2016-05-11;8771~art11` — As autoridades administrativas a que se refere o art. 10, § 3º da Lei nº 12.965, de 2014 , indicarão o fundamento legal de competência expressa para …
- `core` → `urn:lex:br:federal:lei:2014-04-23;12965~art10;par3` — O disposto no caput não impede o acesso aos dados cadastrais que informem qualificação pessoal, filiação e endereço, na forma da lei, pelas autoridad…
- `supporting` → `urn:lex:br:federal:decreto:2016-05-11;8771~art11;par1` — O provedor que não coletar dados cadastrais deverá informar tal fato à autoridade solicitante, ficando desobrigado de fornecer tais dados.
- `supporting` → `urn:lex:br:federal:decreto:2016-05-11;8771~art11;par2` — São considerados dados cadastrais:
- `supporting` → `urn:lex:br:federal:decreto:2016-05-11;8771~art11;par2;inc1` — a filiação;
- `supporting` → `urn:lex:br:federal:decreto:2016-05-11;8771~art11;par2;inc2` — o endereço; e
- `supporting` → `urn:lex:br:federal:decreto:2016-05-11;8771~art11;par2;inc3` — a qualificação pessoal, entendida como nome, prenome, estado civil e profissão do usuário.
- `supporting` → `urn:lex:br:federal:decreto:2016-05-11;8771~art11;par3` — Os pedidos de que trata o caput devem especificar os indivíduos cujos dados estão sendo requeridos e as informações desejadas, sendo vedados pedidos …

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.5616)  ◐ supporting
- URN: `urn:lex:br:federal:decreto:2016-05-11;8771~art11;par2;inc3`
- nav: III - DA PROTEÇÃO AOS REGISTROS, AOS DADOS PESSOAIS E ÀS COMUNICAÇÕES PRIVADAS > I - Da requisição de dados cadastrais
- text: a qualificação pessoal, entendida como nome, prenome, estado civil e profissão do usuário.

### Rank 2  (sim=0.5559)  ◐ supporting
- URN: `urn:lex:br:federal:decreto:2016-05-11;8771~art11;par2`
- nav: III - DA PROTEÇÃO AOS REGISTROS, AOS DADOS PESSOAIS E ÀS COMUNICAÇÕES PRIVADAS > I - Da requisição de dados cadastrais
- text: São considerados dados cadastrais:

### Rank 3  (sim=0.5553)  ★ core
- URN: `urn:lex:br:federal:decreto:2016-05-11;8771~art11`
- nav: III - DA PROTEÇÃO AOS REGISTROS, AOS DADOS PESSOAIS E ÀS COMUNICAÇÕES PRIVADAS > I - Da requisição de dados cadastrais
- text: As autoridades administrativas a que se refere o art. 10, § 3º da Lei nº 12.965, de 2014 , indicarão o fundamento legal de competência expressa para o acesso e a motivação para o pedido de acesso aos dados cadastrais.

### Rank 4  (sim=0.5541)  ◐ supporting
- URN: `urn:lex:br:federal:decreto:2016-05-11;8771~art11;par2;inc1`
- nav: III - DA PROTEÇÃO AOS REGISTROS, AOS DADOS PESSOAIS E ÀS COMUNICAÇÕES PRIVADAS > I - Da requisição de dados cadastrais
- text: a filiação;

### Rank 5  (sim=0.5539)  ◐ supporting
- URN: `urn:lex:br:federal:decreto:2016-05-11;8771~art11;par2;inc2`
- nav: III - DA PROTEÇÃO AOS REGISTROS, AOS DADOS PESSOAIS E ÀS COMUNICAÇÕES PRIVADAS > I - Da requisição de dados cadastrais
- text: o endereço; e

### Rank 6  (sim=0.5472)  ◐ supporting
- URN: `urn:lex:br:federal:decreto:2016-05-11;8771~art11;par1`
- nav: III - DA PROTEÇÃO AOS REGISTROS, AOS DADOS PESSOAIS E ÀS COMUNICAÇÕES PRIVADAS > I - Da requisição de dados cadastrais
- text: O provedor que não coletar dados cadastrais deverá informar tal fato à autoridade solicitante, ficando desobrigado de fornecer tais dados.

### Rank 7  (sim=0.5438)  ◐ supporting
- URN: `urn:lex:br:federal:decreto:2016-05-11;8771~art11;par3`
- nav: III - DA PROTEÇÃO AOS REGISTROS, AOS DADOS PESSOAIS E ÀS COMUNICAÇÕES PRIVADAS > I - Da requisição de dados cadastrais
- text: Os pedidos de que trata o caput devem especificar os indivíduos cujos dados estão sendo requeridos e as informações desejadas, sendo vedados pedidos coletivos que sejam genéricos ou inespecíficos.

### Rank 8  (sim=0.5368)    
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art29`
- nav: IV DO TRATAMENTO DE DADOS PESSOAIS PELO PODER PÚBLICO > I Das Regras
- text: A autoridade nacional poderá solicitar, a qualquer momento, aos órgãos e às entidades do poder público a realização de operações de tratamento de dados pessoais, informações específicas sobre o âmbito e a natureza dos d…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 9  (sim=0.5368)    
- URN: `urn:lex:br:federal:decreto:2016-05-11;8771~art12;inc1`
- nav: III - DA PROTEÇÃO AOS REGISTROS, AOS DADOS PESSOAIS E ÀS COMUNICAÇÕES PRIVADAS > I - Da requisição de dados cadastrais
- text: o número de pedidos realizados;
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 10  (sim=0.5331)    
- URN: `urn:lex:br:federal:decreto:2016-05-11;8771~art12;inc4`
- nav: III - DA PROTEÇÃO AOS REGISTROS, AOS DADOS PESSOAIS E ÀS COMUNICAÇÕES PRIVADAS > I - Da requisição de dados cadastrais
- text: o número de usuários afetados por tais solicitações.
- `[ ] add as core`
- `[ ] add as supporting`

---

## [9] alguém me ameaçou online, posso processar?

- **MRR@10 atual**: 1.000  |  notes: CP art. 147 (ameaça). Supporting: § 1 (pena em dobro contra mulher), § 2 (procede mediante representação).

**Current gold:**

- `core` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art147` — - Ameaçar alguém, por palavra, escrito ou gesto, ou qualquer outro meio simbólico, de causar-lhe mal injusto e grave:
- `supporting` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art147;par1` — Se o crime é cometido contra a mulher por razões da condição do sexo feminino, nos termos do § 1º do art. 121-A deste Código, aplica-se a pena em dob…
- `supporting` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art147;par2` — Somente se procede mediante representação, exceto na hipótese prevista no § 1º deste artigo.

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.6137)  ◐ supporting
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art147;par2`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > I DOS CRIMES CONTRA A LIBERDADE PESSOAL - Constrangimento ilegal
- text: Somente se procede mediante representação, exceto na hipótese prevista no § 1º deste artigo.

### Rank 2  (sim=0.5969)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art146-a;par1`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > I DOS CRIMES CONTRA A LIBERDADE PESSOAL - Constrangimento ilegal
- text: Se a conduta é realizada por meio da rede de computadores, de rede social, de aplicativos, de jogos on-line ou por qualquer outro meio ou ambiente digital, ou transmitida em tempo real:
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 3  (sim=0.5904)  ★ core
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art147`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > I DOS CRIMES CONTRA A LIBERDADE PESSOAL - Constrangimento ilegal
- text: - Ameaçar alguém, por palavra, escrito ou gesto, ou qualquer outro meio simbólico, de causar-lhe mal injusto e grave:

### Rank 4  (sim=0.5589)  ◐ supporting
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art147;par1`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > I DOS CRIMES CONTRA A LIBERDADE PESSOAL - Constrangimento ilegal
- text: Se o crime é cometido contra a mulher por razões da condição do sexo feminino, nos termos do § 1º do art. 121-A deste Código, aplica-se a pena em dobro.

### Rank 5  (sim=0.5494)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art141;par2`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > V DOS CRIMES CONTRA A HONRA - Calúnia
- text: Se o crime é cometido ou divulgado em quaisquer modalidades das redes sociais da rede mundial de computadores, aplica-se em triplo a pena.
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 6  (sim=0.5461)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art147-a;par3`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > I DOS CRIMES CONTRA A LIBERDADE PESSOAL - Constrangimento ilegal
- text: Somente se procede mediante representação. Violência psicológica contra a mulher Art. 147-B. Causar dano emocional à mulher que a prejudique e perturbe seu pleno desenvolvimento ou que vise a degradar ou a controlar sua…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 7  (sim=0.5385)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art146-a`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > I DOS CRIMES CONTRA A LIBERDADE PESSOAL - Constrangimento ilegal
- text: Intimidar sistematicamente, individualmente ou em grupo, mediante violência física ou psicológica, uma ou mais pessoas, de modo intencional e repetitivo, sem motivação evidente, por meio de atos de intimidação, de humil…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 8  (sim=0.5360)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art145`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > V DOS CRIMES CONTRA A HONRA - Calúnia
- text: - Nos crimes previstos neste Capítulo somente se procede mediante queixa, salvo quando, no caso do art. 140, § 2º, da violência resulta lesão corporal.
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 9  (sim=0.5340)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art122;par4`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > I DOS CRIMES CONTRA A VIDA - Homicídio simples
- text: A pena é aumentada até o dobro se a conduta é realizada por meio da rede de computadores, de rede social ou transmitida em tempo real.
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 10  (sim=0.5324)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art145;par1`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > V DOS CRIMES CONTRA A HONRA - Calúnia
- text: Procede-se mediante requisição do Ministro da Justiça, no caso do inciso I do caput do art. 141 deste Código, e mediante representação do ofendido, no caso do inciso II do mesmo artigo, bem como no caso do § 3o do art. …
- `[ ] add as core`
- `[ ] add as supporting`

---

## [10] clonaram meu cartão pela internet, qual artigo se aplica?

- **MRR@10 atual**: 0.000  |  notes: CDC art. 14 (responsabilidade civil do fornecedor) + CDC art. 39 (práticas abusivas) + CP art. 171 (estelionato, fraude eletrônica após Lei 14155/21). Supporting: CP art. 155 § 4 II (furto qualificado mediante fraude).

**Current gold:**

- `core` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art171` — - Obter, para si ou para outrem, vantagem ilícita, em prejuízo alheio, induzindo ou mantendo alguém em erro, mediante artifício, ardil, ou qualquer o…
- `core` → `urn:lex:br:federal:lei:1990-09-11;8078~art14` — O fornecedor de serviços responde, independentemente da existência de culpa, pela reparação dos danos causados aos consumidores por defeitos relativo…
- `core` → `urn:lex:br:federal:lei:1990-09-11;8078~art39` — É vedado ao fornecedor de produtos ou serviços, dentre outras práticas abusivas:
- `supporting` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art155;par4;inc2` — com abuso de confiança, ou mediante fraude, escalada ou destreza;

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.6283)    
- URN: `urn:lex:br:federal:lei:1990-09-11;8078~art54-g;inc3`
- nav: I Dos Direitos do Consumidor > VI-A
- text: impedir ou dificultar, em caso de utilização fraudulenta do cartão de crédito ou similar, que o consumidor peça e obtenha, quando aplicável, a anulação ou o imediato bloqueio do pagamento, ou ainda a restituição dos val…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 2  (sim=0.6243)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art298;par1`
- nav: ESPECIAL > X DOS CRIMES CONTRA A FÉ PÚBLICA > III DA FALSIDADE DOCUMENTAL - Falsificação do selo ou sinal público
- text: Para fins do disposto no caput, equipara-se a documento particular o cartão de crédito ou débito. Vigência
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 3  (sim=0.5987)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art171;par2;inc3`
- nav: ESPECIAL > II DOS CRIMES CONTRA O PATRIMÔNIO > VI DO ESTELIONATO E OUTRAS FRAUDES - Estelionato
- text: defrauda, mediante alienação não consentida pelo credor ou por outro modo, a garantia pignoratícia, quando tem a posse do objeto empenhado;
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 4  (sim=0.5928)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par5;inc2`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: Presidente do Supremo Tribunal Federal; Vigência
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 5  (sim=0.5917)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art171;par2`
- nav: ESPECIAL > II DOS CRIMES CONTRA O PATRIMÔNIO > VI DO ESTELIONATO E OUTRAS FRAUDES - Estelionato
- text: -B. A pena prevista no § 2º-A deste artigo, considerada a relevância do resultado gravoso, aumenta-se de 1/3 (um terço) a 2/3 (dois terços), se o crime é praticado mediante a utilização de servidor mantido fora do terri…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 6  (sim=0.5906)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par5`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: o Aumenta-se a pena de um terço à metade se o crime for praticado contra: Vigência
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 7  (sim=0.5904)    
- URN: `urn:lex:br:federal:lei:2014-04-23;12965~art7;inc13`
- nav: II DOS DIREITOS E GARANTIAS DOS USUÁRIOS > I - Disposições gerais
- text: aplicação das normas de proteção e defesa do consumidor nas relações de consumo realizadas na internet.
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 8  (sim=0.5853)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: Invadir dispositivo informático de uso alheio, conectado ou não à rede de computadores, com o fim de obter, adulterar ou destruir dados ou informações sem autorização expressa ou tácita do usuário do dispositivo ou de i…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 9  (sim=0.5839)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par2`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: Aumenta-se a pena de 1/3 (um terço) a 2/3 (dois terços) se da invasão resulta prejuízo econômico.
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 10  (sim=0.5816)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par3`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: o Se da invasão resultar a obtenção de conteúdo de comunicações eletrônicas privadas, segredos comerciais ou industriais, informações sigilosas, assim definidas em lei, ou o controle remoto não autorizado do dispositivo…
- `[ ] add as core`
- `[ ] add as supporting`

---

## [11] publicaram fotos íntimas minhas sem autorização, isso é crime?

- **MRR@10 atual**: 1.000  |  notes: CP art. 218-C (divulgação de cena íntima) + art. 216-B (produzir/fotografar sem autorização — conduta paralela). Supporting: § 1 do 216-B (montagem); § 1 do 218-C (qualificadora); § 2 do 218-C (excludente jornalístico/científico).

**Current gold:**

- `core` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art216-b` — Produzir, fotografar, filmar ou registrar, por qualquer meio, conteúdo com cena de nudez ou ato sexual ou libidinoso de caráter íntimo e privado sem …
- `core` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art218-c` — Oferecer, trocar, disponibilizar, transmitir, vender ou expor à venda, distribuir, publicar ou divulgar, por qualquer meio - inclusive por meio de co…
- `supporting` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art216-b;par1` — Na mesma pena incorre quem realiza montagem em fotografia, vídeo, áudio ou qualquer outro registro com o fim de incluir pessoa em cena de nudez ou at…
- `supporting` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art218-c;par1` — A pena é aumentada de 1/3 (um terço) a 2/3 (dois terços) se o crime é praticado por agente que mantém ou tenha mantido relação íntima de afeto com a …
- `supporting` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art218-c;par2` — Não há crime quando o agente pratica as condutas descritas no caput deste artigo em publicação de natureza jornalística, científica, cultural ou acad…

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.6449)  ★ core
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art216-b`
- nav: ESPECIAL > VI DOS CRIMES CONTRA A DIGNIDADE SEXUAL > I-A
- text: Produzir, fotografar, filmar ou registrar, por qualquer meio, conteúdo com cena de nudez ou ato sexual ou libidinoso de caráter íntimo e privado sem autorização dos participantes:

### Rank 2  (sim=0.6381)  ◐ supporting
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art216-b;par1`
- nav: ESPECIAL > VI DOS CRIMES CONTRA A DIGNIDADE SEXUAL > I-A
- text: Na mesma pena incorre quem realiza montagem em fotografia, vídeo, áudio ou qualquer outro registro com o fim de incluir pessoa em cena de nudez ou ato sexual ou libidinoso de caráter íntimo.

### Rank 3  (sim=0.6264)  ◐ supporting
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art218-c;par2`
- nav: ESPECIAL > VI DOS CRIMES CONTRA A DIGNIDADE SEXUAL > II DOS CRIMES SEXUAIS CONTRA VULNERÁVEL
- text: Não há crime quando o agente pratica as condutas descritas no caput deste artigo em publicação de natureza jornalística, científica, cultural ou acadêmica com a adoção de recurso que impossibilite a identificação da vít…

### Rank 4  (sim=0.6155)  ★ core
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art218-c`
- nav: ESPECIAL > VI DOS CRIMES CONTRA A DIGNIDADE SEXUAL > II DOS CRIMES SEXUAIS CONTRA VULNERÁVEL
- text: Oferecer, trocar, disponibilizar, transmitir, vender ou expor à venda, distribuir, publicar ou divulgar, por qualquer meio - inclusive por meio de comunicação de massa ou sistema de informática ou telemática -, fotograf…

### Rank 5  (sim=0.6031)  ◐ supporting
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art218-c;par1`
- nav: ESPECIAL > VI DOS CRIMES CONTRA A DIGNIDADE SEXUAL > II DOS CRIMES SEXUAIS CONTRA VULNERÁVEL
- text: A pena é aumentada de 1/3 (um terço) a 2/3 (dois terços) se o crime é praticado por agente que mantém ou tenha mantido relação íntima de afeto com a vítima ou com o fim de vingança ou humilhação.

### Rank 6  (sim=0.5706)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art234;par1`
- nav: ESPECIAL > VI DOS CRIMES CONTRA A DIGNIDADE SEXUAL > VI DO ULTRAJE PÚBLICO AO PUDOR
- text: - Incorre na mesma pena quem:
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 7  (sim=0.5652)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art234;par1;inc1`
- nav: ESPECIAL > VI DOS CRIMES CONTRA A DIGNIDADE SEXUAL > VI DO ULTRAJE PÚBLICO AO PUDOR
- text: vende, distribui ou expõe à venda ou ao público qualquer dos objetos referidos neste artigo;
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 8  (sim=0.5639)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art234`
- nav: ESPECIAL > VI DOS CRIMES CONTRA A DIGNIDADE SEXUAL > VI DO ULTRAJE PÚBLICO AO PUDOR
- text: - Fazer, importar, exportar, adquirir ou ter sob sua guarda, para fim de comércio, de distribuição ou de exposição pública, escrito, desenho, pintura, estampa ou qualquer objeto obsceno:
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 9  (sim=0.5632)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art225`
- nav: ESPECIAL > VI DOS CRIMES CONTRA A DIGNIDADE SEXUAL > IV DISPOSIÇÕES GERAIS
- text: Nos crimes definidos nos Capítulos I e II deste Título, procede-se mediante ação penal pública incondicionada.
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 10  (sim=0.5623)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art234;par1;inc3`
- nav: ESPECIAL > VI DOS CRIMES CONTRA A DIGNIDADE SEXUAL > VI DO ULTRAJE PÚBLICO AO PUDOR
- text: realiza, em lugar público ou acessível ao público, ou pelo rádio, audição ou recitação de caráter obsceno.
- `[ ] add as core`
- `[ ] add as supporting`

---

## [12] criaram um perfil falso com meu nome nas redes, há crime?

- **MRR@10 atual**: 1.000  |  notes: CP art. 307 (falsa identidade). Supporting: art. 141 § 2 (pena triplicada quando calúnia/difamação em rede social — frequentemente conexo a perfil falso).

**Current gold:**

- `core` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art307` — - Atribuir-se ou atribuir a terceiro falsa identidade para obter vantagem, em proveito próprio ou alheio, ou para causar dano a outrem:
- `supporting` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art141;par2` — Se o crime é cometido ou divulgado em quaisquer modalidades das redes sociais da rede mundial de computadores, aplica-se em triplo a pena.

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.5885)  ★ core
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art307`
- nav: ESPECIAL > X DOS CRIMES CONTRA A FÉ PÚBLICA > IV DE OUTRAS FALSIDADES - Falsificação do sinal empregado no contraste de metal precioso ou na fiscalização alfandegária, ou para outros fins
- text: - Atribuir-se ou atribuir a terceiro falsa identidade para obter vantagem, em proveito próprio ou alheio, ou para causar dano a outrem:

### Rank 2  (sim=0.5710)    
- URN: `urn:lex:br:federal:lei:2014-04-23;12965~art8;par1;inc2;ali-g`
- nav: II DOS DIREITOS E GARANTIAS DOS USUÁRIOS > II - Dos direitos e das garantias dos usuários de redes sociais
- text: utilização ou ensino do uso de computadores ou tecnologia da informação com o objetivo de roubar credenciais, invadir sistemas, comprometer dados pessoais ou causar danos a terceiros; (Rejeitada)
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 3  (sim=0.5547)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art309`
- nav: ESPECIAL > X DOS CRIMES CONTRA A FÉ PÚBLICA > IV DE OUTRAS FALSIDADES - Falsificação do sinal empregado no contraste de metal precioso ou na fiscalização alfandegária, ou para outros fins
- text: - Usar o estrangeiro, para entrar ou permanecer no território nacional, nome que não é o seu:
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 4  (sim=0.5539)  ◐ supporting
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art141;par2`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > V DOS CRIMES CONTRA A HONRA - Calúnia
- text: Se o crime é cometido ou divulgado em quaisquer modalidades das redes sociais da rede mundial de computadores, aplica-se em triplo a pena.

### Rank 5  (sim=0.5524)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art309;par1`
- nav: ESPECIAL > X DOS CRIMES CONTRA A FÉ PÚBLICA > IV DE OUTRAS FALSIDADES - Falsificação do sinal empregado no contraste de metal precioso ou na fiscalização alfandegária, ou para outros fins
- text: - Atribuir a estrangeiro falsa qualidade para promover-lhe a entrada em território nacional:
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 6  (sim=0.5502)    
- URN: `urn:lex:br:federal:lei:2014-04-23;12965~art8;par1;inc3`
- nav: II DOS DIREITOS E GARANTIAS DOS USUÁRIOS > II - Dos direitos e das garantias dos usuários de redes sociais
- text: requerimento do ofendido, de seu representante legal ou de seus herdeiros, na hipótese de violação à intimidade, à privacidade, à imagem, à honra, à proteção de seus dados pessoais ou à propriedade intelectual; ou (Reje…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 7  (sim=0.5437)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art146-a;par1`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > I DOS CRIMES CONTRA A LIBERDADE PESSOAL - Constrangimento ilegal
- text: Se a conduta é realizada por meio da rede de computadores, de rede social, de aplicativos, de jogos on-line ou por qualquer outro meio ou ambiente digital, ou transmitida em tempo real:
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 8  (sim=0.5397)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > VI DOS CRIMES CONTRA A LIBERDADE INDIVIDUAL > IV DOS CRIMES CONTRA A INVIOLABILIDADE DOS SEGREDOS - Divulgação de segredo
- text: Invadir dispositivo informático de uso alheio, conectado ou não à rede de computadores, com o fim de obter, adulterar ou destruir dados ou informações sem autorização expressa ou tácita do usuário do dispositivo ou de i…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 9  (sim=0.5394)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art308`
- nav: ESPECIAL > X DOS CRIMES CONTRA A FÉ PÚBLICA > IV DE OUTRAS FALSIDADES - Falsificação do sinal empregado no contraste de metal precioso ou na fiscalização alfandegária, ou para outros fins
- text: - Usar, como próprio, passaporte, título de eleitor, caderneta de reservista ou qualquer documento de identidade alheia ou ceder a outrem, para que dele se utilize, documento dessa natureza, próprio ou de terceiro:
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 10  (sim=0.5387)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art298;par1`
- nav: ESPECIAL > X DOS CRIMES CONTRA A FÉ PÚBLICA > III DA FALSIDADE DOCUMENTAL - Falsificação do selo ou sinal público
- text: Para fins do disposto no caput, equipara-se a documento particular o cartão de crédito ou débito. Vigência
- `[ ] add as core`
- `[ ] add as supporting`

---

## [13] tenho direito de saber o que o governo guarda sobre mim?

- **MRR@10 atual**: 1.000  |  notes: CF art. 5 LXXII (habeas data) + alínea-a (objeto: registros governamentais) + LAI art. 1 § 1 II (entidades sujeitas) + art. 10 (pedido de acesso) + art. 11 (resposta imediata/prazo) + LGPD art. 1 (escopo) + art. 18 (direitos do titular). Supporting: CF art. 5 XXXIII (info órgãos públicos).

**Current gold:**

- `core` → `urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc72` — conceder-se-á "habeas-data":
- `core` → `urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc72;ali-a` — para assegurar o conhecimento de informações relativas à pessoa do impetrante, constantes de registros ou bancos de dados de entidades governamentais…
- `core` → `urn:lex:br:federal:lei:2011-11-18;12527~art10` — Qualquer interessado poderá apresentar pedido de acesso a informações aos órgãos e entidades referidos no art. 1º desta Lei, por qualquer meio legíti…
- `core` → `urn:lex:br:federal:lei:2011-11-18;12527~art11` — O órgão ou entidade pública deverá autorizar ou conceder o acesso imediato à informação disponível.
- `core` → `urn:lex:br:federal:lei:2011-11-18;12527~art1;par1;inc2` — as autarquias, as fundações públicas, as empresas públicas, as sociedades de economia mista e demais entidades controladas direta ou indiretamente pe…
- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art1` — Esta Lei dispõe sobre o tratamento de dados pessoais, inclusive nos meios digitais, por pessoa natural ou por pessoa jurídica de direito público ou p…
- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art18` — O titular dos dados pessoais tem direito a obter do controlador, em relação aos dados do titular por ele tratados, a qualquer momento e mediante requ…
- `supporting` → `urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc33` — todos têm direito a receber dos órgãos públicos informações de seu interesse particular, ou de interesse coletivo ou geral, que serão prestadas no pr…

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.6514)  ★ core
- URN: `urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc72;ali-a`
- nav: II - Dos Direitos e Garantias Fundamentais > I - DOS DIREITOS E DEVERES INDIVIDUAIS E COLETIVOS
- text: para assegurar o conhecimento de informações relativas à pessoa do impetrante, constantes de registros ou bancos de dados de entidades governamentais ou de caráter público;

### Rank 2  (sim=0.6213)  ◐ supporting
- URN: `urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc33`
- nav: II - Dos Direitos e Garantias Fundamentais > I - DOS DIREITOS E DEVERES INDIVIDUAIS E COLETIVOS
- text: todos têm direito a receber dos órgãos públicos informações de seu interesse particular, ou de interesse coletivo ou geral, que serão prestadas no prazo da lei, sob pena de responsabilidade, ressalvadas aquelas cujo sig…

### Rank 3  (sim=0.6162)    
- URN: `urn:lex:br:federal:lei:2011-11-18;12527~art7;inc2`
- nav: II - DO ACESSO A INFORMAÇÕES E DA SUA DIVULGAÇÃO
- text: informação contida em registros ou documentos, produzidos ou acumulados por seus órgãos ou entidades, recolhidos ou não a arquivos públicos;
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 4  (sim=0.6104)    
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art18;inc1`
- nav: III DOS DIREITOS DO TITULAR
- text: confirmação da existência de tratamento;
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 5  (sim=0.6084)    
- URN: `urn:lex:br:federal:decreto:2016-05-11;8771~art12;inc1`
- nav: III - DA PROTEÇÃO AOS REGISTROS, AOS DADOS PESSOAIS E ÀS COMUNICAÇÕES PRIVADAS > I - Da requisição de dados cadastrais
- text: o número de pedidos realizados;
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 6  (sim=0.6083)    
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art19;par2`
- nav: III DOS DIREITOS DO TITULAR
- text: As informações e os dados poderão ser fornecidos, a critério do titular:
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 7  (sim=0.6056)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art18`
- nav: III DOS DIREITOS DO TITULAR
- text: O titular dos dados pessoais tem direito a obter do controlador, em relação aos dados do titular por ele tratados, a qualquer momento e mediante requisição:

### Rank 8  (sim=0.6037)    
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art19`
- nav: III DOS DIREITOS DO TITULAR
- text: A confirmação de existência ou o acesso a dados pessoais serão providenciados, mediante requisição do titular:
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 9  (sim=0.6033)    
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art19;inc2`
- nav: III DOS DIREITOS DO TITULAR
- text: por meio de declaração clara e completa, que indique a origem dos dados, a inexistência de registro, os critérios utilizados e a finalidade do tratamento, observados os segredos comercial e industrial, fornecida no praz…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 10  (sim=0.6030)    
- URN: `urn:lex:br:federal:decreto:2016-05-11;8771~art12`
- nav: III - DA PROTEÇÃO AOS REGISTROS, AOS DADOS PESSOAIS E ÀS COMUNICAÇÕES PRIVADAS > I - Da requisição de dados cadastrais
- text: A autoridade máxima de cada órgão da administração pública federal publicará anualmente em seu sítio na internet relatórios estatísticos de requisição de dados cadastrais, contendo:
- `[ ] add as core`
- `[ ] add as supporting`

---

## [14] podem me processar por escrever opinião na internet?

- **MRR@10 atual**: 0.333  |  notes: Resposta literal: CP art. 138 (calúnia), 139 (difamação), 140 (injúria) — crimes que podem ser imputados. Supporting: MCI art. 10 § 1 (provedor disponibiliza dados que identificam o usuário, operacionaliza o não-anonimato); CF art. 220 (liberdade de manifestação como contexto de proteção).

**Current gold:**

- `core` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art138` — - Caluniar alguém, imputando-lhe falsamente fato definido como crime:
- `core` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art139` — - Difamar alguém, imputando-lhe fato ofensivo à sua reputação:
- `core` → `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art140` — - Injuriar alguém, ofendendo-lhe a dignidade ou o decoro:
- `supporting` → `urn:lex:br:federal:constituicao:1988-10-05;1988~art220` — A manifestação do pensamento, a criação, a expressão e a informação, sob qualquer forma, processo ou veículo não sofrerão qualquer restrição, observa…
- `supporting` → `urn:lex:br:federal:lei:2014-04-23;12965~art10;par1` — O provedor responsável pela guarda somente será obrigado a disponibilizar os registros mencionados no caput, de forma autônoma ou associados a dados …

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.5833)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art142;inc2`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > V DOS CRIMES CONTRA A HONRA - Calúnia
- text: a opinião desfavorável da crítica literária, artística ou científica, salvo quando inequívoca a intenção de injuriar ou difamar;
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 2  (sim=0.5791)    
- URN: `urn:lex:br:federal:lei:2014-04-23;12965~art19;par3`
- nav: III DA PROVISÃO DE CONEXÃO E DE APLICAÇÕES DE INTERNET > III Da Responsabilidade por Danos Decorrentes de Conteúdo Gerado por Terceiros
- text: As causas que versem sobre ressarcimento por danos decorrentes de conteúdos disponibilizados na internet relacionados à honra, à reputação ou a direitos de personalidade, bem como sobre a indisponibilização desses conte…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 3  (sim=0.5751)  ◐ supporting
- URN: `urn:lex:br:federal:constituicao:1988-10-05;1988~art220`
- nav: VIII - Da Ordem Social > V - DA COMUNICAÇÃO SOCIAL
- text: A manifestação do pensamento, a criação, a expressão e a informação, sob qualquer forma, processo ou veículo não sofrerão qualquer restrição, observado o disposto nesta Constituição.

### Rank 4  (sim=0.5674)    
- URN: `urn:lex:br:federal:constituicao:1988-10-05;1988~art220;par3`
- nav: VIII - Da Ordem Social > V - DA COMUNICAÇÃO SOCIAL
- text: Compete à lei federal:
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 5  (sim=0.5671)    
- URN: `urn:lex:br:federal:lei:2014-04-23;12965~art8;par1;inc1`
- nav: II DOS DIREITOS E GARANTIAS DOS USUÁRIOS > II - Dos direitos e das garantias dos usuários de redes sociais
- text: quando o conteúdo publicado pelo usuário estiver em desacordo com o disposto na Lei nº 8.069, de 13 de julho de 1990; (Rejeitada)
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 6  (sim=0.5667)    
- URN: `urn:lex:br:federal:lei:2014-04-23;12965~art19;par2`
- nav: III DA PROVISÃO DE CONEXÃO E DE APLICAÇÕES DE INTERNET > III Da Responsabilidade por Danos Decorrentes de Conteúdo Gerado por Terceiros
- text: A aplicação do disposto neste artigo para infrações a direitos de autor ou a direitos conexos depende de previsão legal específica, que deverá respeitar a liberdade de expressão e demais garantias previstas no art. 5º d…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 7  (sim=0.5651)    
- URN: `urn:lex:br:federal:lei:2014-04-23;12965~art19`
- nav: III DA PROVISÃO DE CONEXÃO E DE APLICAÇÕES DE INTERNET > III Da Responsabilidade por Danos Decorrentes de Conteúdo Gerado por Terceiros
- text: Com o intuito de assegurar a liberdade de expressão e impedir a censura, o provedor de aplicações de internet somente poderá ser responsabilizado civilmente por danos decorrentes de conteúdo gerado por terceiros se, apó…
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 8  (sim=0.5618)    
- URN: `urn:lex:br:federal:lei:2014-04-23;12965~art8;par1;inc2;ali-h`
- nav: II DOS DIREITOS E GARANTIAS DOS USUÁRIOS > II - Dos direitos e das garantias dos usuários de redes sociais
- text: prática, apoio, promoção ou incitação de atos contra a segurança pública, defesa nacional ou segurança do Estado; (Rejeitada)
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 9  (sim=0.5583)    
- URN: `urn:lex:br:federal:constituicao:1988-10-05;1988~art220;par2`
- nav: VIII - Da Ordem Social > V - DA COMUNICAÇÃO SOCIAL
- text: É vedada toda e qualquer censura de natureza política, ideológica e artística.
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 10  (sim=0.5580)    
- URN: `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art142;inc3`
- nav: ESPECIAL > I DOS CRIMES CONTRA A PESSOA > V DOS CRIMES CONTRA A HONRA - Calúnia
- text: o conceito desfavorável emitido por funcionário público, em apreciação ou informação que preste no cumprimento de dever do ofício.
- `[ ] add as core`
- `[ ] add as supporting`

---

## [15] minha empresa precisa nomear alguém responsável pelos dados dos clientes?

- **MRR@10 atual**: 1.000  |  notes: LGPD art. 41 caput (exigência de encarregado). Supporting: § 1 (identidade pública) + § 2 (atividades) + incs (atribuições) + § 3 (autoridade nacional define dispensa) + art. 5 VIII (definição de encarregado).

**Current gold:**

- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art41` — O controlador deverá indicar encarregado pelo tratamento de dados pessoais.
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art41;par1` — A identidade e as informações de contato do encarregado deverão ser divulgadas publicamente, de forma clara e objetiva, preferencialmente no sítio el…
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art41;par2` — As atividades do encarregado consistem em:
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art41;par2;inc1` — aceitar reclamações e comunicações dos titulares, prestar esclarecimentos e adotar providências;
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art41;par2;inc2` — receber comunicações da autoridade nacional e adotar providências;
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art41;par2;inc3` — orientar os funcionários e os contratados da entidade a respeito das práticas a serem tomadas em relação à proteção de dados pessoais; e
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art41;par2;inc4` — executar as demais atribuições determinadas pelo controlador ou estabelecidas em normas complementares.
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art41;par3` — A autoridade nacional poderá estabelecer normas complementares sobre a definição e as atribuições do encarregado, inclusive hipóteses de dispensa da …
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art5;inc8` — encarregado: pessoa indicada pelo controlador e operador para atuar como canal de comunicação entre o controlador, os titulares dos dados e a Agência…

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.6673)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art41;par3`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > II Do Encarregado pelo Tratamento de Dados Pessoais
- text: A autoridade nacional poderá estabelecer normas complementares sobre a definição e as atribuições do encarregado, inclusive hipóteses de dispensa da necessidade de sua indicação, conforme a natureza e o porte da entidad…

### Rank 2  (sim=0.6643)    
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art41;par4`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > II Do Encarregado pelo Tratamento de Dados Pessoais
- text: (VETADO). Vigência
- `[ ] add as core`
- `[ ] add as supporting`

### Rank 3  (sim=0.6612)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art41;par2;inc3`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > II Do Encarregado pelo Tratamento de Dados Pessoais
- text: orientar os funcionários e os contratados da entidade a respeito das práticas a serem tomadas em relação à proteção de dados pessoais; e

### Rank 4  (sim=0.6606)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art41`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > II Do Encarregado pelo Tratamento de Dados Pessoais
- text: O controlador deverá indicar encarregado pelo tratamento de dados pessoais.

### Rank 5  (sim=0.6547)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art41;par2`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > II Do Encarregado pelo Tratamento de Dados Pessoais
- text: As atividades do encarregado consistem em:

### Rank 6  (sim=0.6513)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art41;par2;inc1`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > II Do Encarregado pelo Tratamento de Dados Pessoais
- text: aceitar reclamações e comunicações dos titulares, prestar esclarecimentos e adotar providências;

### Rank 7  (sim=0.6512)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art41;par1`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > II Do Encarregado pelo Tratamento de Dados Pessoais
- text: A identidade e as informações de contato do encarregado deverão ser divulgadas publicamente, de forma clara e objetiva, preferencialmente no sítio eletrônico do controlador.

### Rank 8  (sim=0.6506)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art41;par2;inc4`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > II Do Encarregado pelo Tratamento de Dados Pessoais
- text: executar as demais atribuições determinadas pelo controlador ou estabelecidas em normas complementares.

### Rank 9  (sim=0.6497)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art41;par2;inc2`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > II Do Encarregado pelo Tratamento de Dados Pessoais
- text: receber comunicações da autoridade nacional e adotar providências;

### Rank 10  (sim=0.6300)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art5;inc8`
- nav: I DISPOSIÇÕES PRELIMINARES
- text: encarregado: pessoa indicada pelo controlador e operador para atuar como canal de comunicação entre o controlador, os titulares dos dados e a Agência Nacional de Proteção de Dados (ANPD);

---

## [16] se vazaram dados e eu sofri prejuízo, quem responde?

- **MRR@10 atual**: 1.000  |  notes: LGPD art. 42 (responsabilidade civil) + art. 43 (excludentes). Supporting: §§ 1-4 do art. 42 (efetiva indenização, solidariedade, ônus, ações coletivas, regresso); art. 43 III (excludente de culpa); art. 44 § 1 (responde quem deixou de adotar segurança); art. 45 (relações de consumo).

**Current gold:**

- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art42` — O controlador ou o operador que, em razão do exercício de atividade de tratamento de dados pessoais, causar a outrem dano patrimonial, moral, individ…
- `core` → `urn:lex:br:federal:lei:2018-08-14;13709~art43` — Os agentes de tratamento só não serão responsabilizados quando provarem:
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art42;par1` — A fim de assegurar a efetiva indenização ao titular dos dados:
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art42;par1;inc1` — o operador responde solidariamente pelos danos causados pelo tratamento quando descumprir as obrigações da legislação de proteção de dados ou quando …
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art42;par1;inc2` — os controladores que estiverem diretamente envolvidos no tratamento do qual decorreram danos ao titular dos dados respondem solidariamente, salvo nos…
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art42;par2` — O juiz, no processo civil, poderá inverter o ônus da prova a favor do titular dos dados quando, a seu juízo, for verossímil a alegação, houver hiposs…
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art42;par3` — As ações de reparação por danos coletivos que tenham por objeto a responsabilização nos termos do caput deste artigo podem ser exercidas coletivament…
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art42;par4` — Aquele que reparar o dano ao titular tem direito de regresso contra os demais responsáveis, na medida de sua participação no evento danoso.
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art43;inc3` — que o dano é decorrente de culpa exclusiva do titular dos dados ou de terceiro.
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art44;par1` — Responde pelos danos decorrentes da violação da segurança dos dados o controlador ou o operador que, ao deixar de adotar as medidas de segurança prev…
- `supporting` → `urn:lex:br:federal:lei:2018-08-14;13709~art45` — As hipóteses de violação do direito do titular no âmbito das relações de consumo permanecem sujeitas às regras de responsabilidade previstas na legis…

**Top-10 retrieved (voyage dense):**

### Rank 1  (sim=0.6982)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art42;par4`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > III Da Responsabilidade e do Ressarcimento de Danos
- text: Aquele que reparar o dano ao titular tem direito de regresso contra os demais responsáveis, na medida de sua participação no evento danoso.

### Rank 2  (sim=0.6873)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art42;par1`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > III Da Responsabilidade e do Ressarcimento de Danos
- text: A fim de assegurar a efetiva indenização ao titular dos dados:

### Rank 3  (sim=0.6857)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art42;par2`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > III Da Responsabilidade e do Ressarcimento de Danos
- text: O juiz, no processo civil, poderá inverter o ônus da prova a favor do titular dos dados quando, a seu juízo, for verossímil a alegação, houver hipossuficiência para fins de produção de prova ou quando a produção de prov…

### Rank 4  (sim=0.6822)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art42;par1;inc2`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > III Da Responsabilidade e do Ressarcimento de Danos
- text: os controladores que estiverem diretamente envolvidos no tratamento do qual decorreram danos ao titular dos dados respondem solidariamente, salvo nos casos de exclusão previstos no art. 43 desta Lei.

### Rank 5  (sim=0.6813)  ★ core
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art42`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > III Da Responsabilidade e do Ressarcimento de Danos
- text: O controlador ou o operador que, em razão do exercício de atividade de tratamento de dados pessoais, causar a outrem dano patrimonial, moral, individual ou coletivo, em violação à legislação de proteção de dados pessoai…

### Rank 6  (sim=0.6803)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art42;par3`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > III Da Responsabilidade e do Ressarcimento de Danos
- text: As ações de reparação por danos coletivos que tenham por objeto a responsabilização nos termos do caput deste artigo podem ser exercidas coletivamente em juízo, observado o disposto na legislação pertinente.

### Rank 7  (sim=0.6773)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art44;par1`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > III Da Responsabilidade e do Ressarcimento de Danos
- text: Responde pelos danos decorrentes da violação da segurança dos dados o controlador ou o operador que, ao deixar de adotar as medidas de segurança previstas no art. 46 desta Lei, der causa ao dano.

### Rank 8  (sim=0.6730)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art42;par1;inc1`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > III Da Responsabilidade e do Ressarcimento de Danos
- text: o operador responde solidariamente pelos danos causados pelo tratamento quando descumprir as obrigações da legislação de proteção de dados ou quando não tiver seguido as instruções lícitas do controlador, hipótese em qu…

### Rank 9  (sim=0.6674)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art45`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > III Da Responsabilidade e do Ressarcimento de Danos
- text: As hipóteses de violação do direito do titular no âmbito das relações de consumo permanecem sujeitas às regras de responsabilidade previstas na legislação pertinente.

### Rank 10  (sim=0.6445)  ◐ supporting
- URN: `urn:lex:br:federal:lei:2018-08-14;13709~art43;inc3`
- nav: VI DOS AGENTES DE TRATAMENTO DE DADOS PESSOAIS > III Da Responsabilidade e do Ressarcimento de Danos
- text: que o dano é decorrente de culpa exclusiva do titular dos dados ou de terceiro.

---
