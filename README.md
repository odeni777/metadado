# DocxMetaEditor

Aplicação web em português para visualizar, editar e limpar propriedades de arquivos do Microsoft Word. O servidor usa Flask, `zipfile` e `lxml`. A interface usa HTML, Tailwind CSS e JavaScript sem framework.

## Executar localmente

Requer Python 3.10 ou superior.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m flask --app docxmeta run
```

No Windows, ative o ambiente com `.venv\\Scripts\\activate`. No navegador, abra o endereço mostrado pelo Flask. O CSS compilado acompanha o código. Para reconstruí-lo após editar a interface, use Node.js 20 ou superior, `npm ci` e `npm run build`.

Para implantação, aponte um servidor WSGI de produção para `docxmeta:app`. Configure HTTPS e limites de requisição compatíveis com os 20 MB aceitos pela aplicação.

## Uso

1. Selecione ou arraste um arquivo `.docx` de até 20 MB.
2. Edite as propriedades gerais, estendidas ou personalizadas. Datas do formulário são em UTC. Ao exibir uma data que contém um deslocamento de fuso, a interface a converte para UTC.
3. Escolha o modo de exportação e baixe a nova cópia.

| Modo | Resultado |
| --- | --- |
| Aplicar alterações | Grava os campos alterados. Limpar um campo geral ou estendido remove o elemento correspondente. |
| Anonimizar / Limpar rastros | Limpa autor, último editor, última impressão, empresa e gerente, redefine a revisão para 1 e o tempo para 0, usa a data e hora UTC atuais para criação e modificação e remove a parte personalizada. |
| Limpar todas as propriedades | Remove as partes gerais, estendidas e personalizadas e suas referências no pacote. |

Novas propriedades aceitam texto, inteiro, decimal, lógico e data/hora. Alguns tipos compostos já presentes podem ser visualizados e removidos. Estruturas adicionais de propriedades estendidas aparecem para consulta.

A limpeza se limita às propriedades OpenXML do pacote. Comentários no corpo do documento, alterações controladas e dados de partes incorporadas permanecem. Editar um pacote assinado pode invalidar suas assinaturas digitais. O Word pode recriar propriedades ao salvar o documento.

## Arquitetura e testes

- `docxmeta/__init__.py` serve a interface e as rotas de leitura e download.
- `docxmeta/openxml.py` implementa a leitura, validação e gravação do pacote. O conteúdo descompactado de cada parte preservada é copiado sem alterações. A tabela de tipos e as relações no nível do pacote são atualizadas quando partes de metadados são criadas ou removidas.
- `docxmeta/templates` e `docxmeta/static` contêm a interface.
- `tests/test_editor.py` verifica leitura, edição, limpeza, validação de entrada e preservação das partes do documento.

```sh
python -m unittest discover -s tests -v
```

O processamento ocorre por requisição, sem banco de dados. A saída é gerada em memória e os arquivos temporários de upload, quando usados pelo Flask, são fechados ao final da requisição.
