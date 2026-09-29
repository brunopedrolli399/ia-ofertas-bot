# Automação do IA Ofertas

Implementação inicial para Bruno. **Não é um robô completo nem está ativada.**
Este módulo é independente do `app.py` atual, que continua tratando OAuth e anúncios
de vendedor. Nenhuma alteração de produção, bio ou publicação foi executada.

## Configuração aplicada

- Instagram: `@iaofertastudo`, confirmado pelo titular como conta Empresa.
- Etiqueta mostrada no gerador de afiliados: `pedrollibruno`.
- Convite para a bio: configurar diretamente no Instagram. O endereço foi omitido
  do repositório público; `whatsapp_invite` permanece vazio. Uma futura integração
  deve recebê-lo por variável de ambiente na hospedagem.
- Grupo comum do WhatsApp, criado no aplicativo; titular confirmou ser administrador.
- Padrões iniciais ajustáveis: três tentativas por dia, fuso de São Paulo e ofertas
  verificadas há no máximo 15 minutos. Estes números são escolhas de implementação.

## Implementado

Preparação de legenda do feed e texto para WhatsApp usando dados de oferta recebidos;
validação de validade, preço, disponibilidade declarada e etiqueta; cliente de publicação
de imagem no feed pela API oficial do Instagram **com Facebook Login**; conferência do
nome da conta autenticada antes de publicar; registro persistente de tentativas;
limite diário e prevenção de duplicidade por produto. A execução padrão é simulação.

O endereço de afiliado recebido é preservado integralmente. O código não inventa
parâmetros de rastreamento nem transforma links comuns em links com comissão.

## Pendências que impedem a operação integral

1. **Coletor e gerador de links do Mercado Livre:** não implementados. Precisam de
   acesso autenticado e autorizado à fonte de ofertas e ao gerador, com confirmação
   de atribuição à conta de Bruno. O OAuth de vendedor do `app.py`, um print, uma
   etiqueta e um exemplo `meli.la` não comprovam esse acesso. Não foi identificada
   uma integração pública de geração de links de afiliado validada para esta conta.
2. **Instagram:** falta conectar a conta por um app Meta. Este cliente utiliza
   Facebook Login, portanto exige Página vinculada, ID do Instagram, token de Página
   válido e permissões compatíveis, incluindo publicação. Não misturar tokens desse
   fluxo com Instagram Login. Conferir a versão Graph suportada no app e configurá-la.
   Renovação de token e fluxo de conexão ainda não implementados. Falhas de autenticação
   interrompem o processamento. Confirmar manualmente o convite na bio antes de ativar.
3. **WhatsApp:** o código apenas prepara o texto; NÃO envia ao grupo. O convite não é
   credencial de API. A Groups API oficial possui requisitos OBA e limite de oito
   participantes e não atende ao grupo de ofertas em crescimento. Não há integração
   não oficial, leitura de mensagens ou conexão de WhatsApp Web neste módulo.
4. **Operação contínua:** falta provisionar um único worker Linux com disco persistente,
   conectar o coletor e instalar agendamento. Não usar disco efêmero ou múltiplos hosts:
   isso perde a proteção de duplicidade. Não foi alterado o serviço Render existente.
5. **Imagens e Stories:** a fonte precisa entregar JPEG público adequado ao feed,
   com autorização de uso. O módulo não cria artes nem publica Stories. Stories com
   preço e chamada precisam de renderização própria; o adesivo de link não é suportado
   na API citada. Estes recursos continuam pendentes.

## Verificar sem publicar

Da raiz do repositório, com as dependências de `requirements.txt` instaladas:

```bash
python automation/worker.py --status
python -m unittest discover -s automation -p 'test_*.py' -v
python automation/worker.py --offers /caminho/ofertas.json
```

O JSON de entrada é um contrato para o **futuro coletor**, não uma exigência de Bruno
montar arquivos diariamente. Deve conter uma lista com no máximo 100 objetos com:
`id` (MLB...), `title`, `price`, `original_price` opcional, `image_url`, `affiliate_url`,
`affiliate_label`, `eligible`, `available` e `checked_at` ISO 8601 com fuso.
O coletor confiável deve verificar preço, disponibilidade, elegibilidade e o link
original da conta. Os campos declarados não provam comissão por si só. Testes usam
dados fictícios e não acessam nenhuma rede.

## Ativação futura do feed

Somente depois de resolver as pendências correspondentes, configurar no ambiente do
worker `IG_USER_ID`, `IG_PAGE_ACCESS_TOKEN`, `META_GRAPH_VERSION`, `STATE_DB` (caminho
absoluto em disco persistente), `BIO_GROUP_LINK_CONFIRMED=true` e `PUBLISH_ENABLED=true`.
Guardar tokens no gerenciador de segredos da hospedagem; nunca no Git, chat ou JSON.
Executar `python automation/worker.py --offers /caminho/ofertas.json --publish`.
Isso publica de verdade; não usar com dados de teste. Essa ativação NÃO habilita WhatsApp.

Cada invocação processa o lote uma vez e encerra. O coletor/agendador futuro deve produzir
dados frescos em cada execução. O limite inclui tentativas falhas e incertas. Produtos
já tentados não são reenviados automaticamente, mesmo no dia seguinte. Em falhas, consultar
as linhas `needs_review`, `reserved`, `processing` ou `publishing` no banco e conferir
o Instagram antes de decidir qualquer reenvio. Uma resposta perdida pode significar
que o post foi publicado. Não apagar o banco para forçar repetição.

## Referências verificadas em 29 de setembro de 2026

- [Coleção oficial Meta Instagram](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)
- [Publicação de mídia](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media)
- [WhatsApp Groups API](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups)
- [Gerador de links Mercado Livre](https://www.mercadolivre.com.br/l/afiliados-gere-seus-links)

Validação executada com mocks, sem autenticação real, chamadas de publicação ou prova
de comissão. Este trabalho deve permanecer em revisão até as integrações serem resolvidas.
