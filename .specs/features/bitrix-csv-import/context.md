# Importação CSV do Bitrix Context

## Confirmed decisions

- O ambiente é demonstrativo; basta importar a primeira linha de cada arquivo selecionado.
- Negócios, Contatos e Empresas usam a coluna `ID` do Bitrix como chave externa.
- Leads sem ID não serão deduplicados por heurística; serão rejeitados com mensagem clara.
- Todas as colunas são preservadas, inclusive nomes repetidos, vazios e campos que o Smart CRM ainda não conhece.
- Registros sem Negócio continuam válidos e entram diretamente em suas próprias coleções.
- Os CSVs fornecidos pelo usuário permanecem fora do repositório; os testes usam arquivos sintéticos sem dados pessoais.

## Remaining dimensions

Autorização, concorrência, expiração e observabilidade são N/A neste protótipo local sem servidor de dados ou usuários simultâneos.
