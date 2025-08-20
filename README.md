# Relatório GitLab – Lista e Comparação de Repositórios entre Dois GitLabs

Ferramenta de linha de comando (CLI) em Python para:
- Listar todos os projetos acessíveis em duas instâncias GitLab diferentes;
- Comparar os projetos existentes em ambas as instâncias pelo caminho do projeto (path_with_namespace);
- Gerar relatórios em arquivos JSON e/ou CSV, incluindo relatórios separados por instância e o conjunto comum;
- Operar com paginação explícita, com logs por página e retentativas automáticas para erros transitórios (500/502/503/504/429).


## Pré‑requisitos
- Python 3.8+
- Dependências Python:
  - python-gitlab (veja requirements.txt)

Instalação das dependências:
```
pip install -r requirements.txt
```

Observação: o comando `--help` do script depende do `python-gitlab`. Se a biblioteca não estiver instalada, o script exibirá um erro ao iniciar. Instale as dependências antes.


## Autenticação e variáveis de ambiente
Você pode fornecer URLs e tokens via parâmetros ou através de variáveis de ambiente:
- GITLAB_URL_1, GITLAB_TOKEN_1
- GITLAB_URL_2, GITLAB_TOKEN_2

Exemplo com variáveis de ambiente:
```
export GITLAB_URL_1=https://gitlab.empresa-a.com
export GITLAB_TOKEN_1=<TOKEN_A>
export GITLAB_URL_2=https://gitlab.empresa-b.com
export GITLAB_TOKEN_2=<TOKEN_B>
```


## Uso rápido
Gera o relatório combinado em JSON:
```
python gitlab_compare.py \
  --url1 https://gitlab.empresa-a.com --token1 $GITLAB_TOKEN_1 \
  --url2 https://gitlab.empresa-b.com --token2 $GITLAB_TOKEN_2 \
  --out-json reports/combined.json
```

Gera o relatório combinado em CSV com paginação customizada, retentativas e salva logs em arquivo:
```
python gitlab_compare.py \
  --url1 https://gitlab.empresa-a.com --token1 $GITLAB_TOKEN_1 \
  --url2 https://gitlab.empresa-b.com --token2 $GITLAB_TOKEN_2 \
  --per-page 100 --max-retries 6 --retry-backoff 2.0 \
  --log-file reports/fetch.log \
  --out-csv reports/combined.csv
```

Gerar relatórios separados por instância e o conjunto comum (JSON e CSV):
```
python gitlab_compare.py \
  --url1 https://gitlab.a --token1 $GITLAB_TOKEN_1 \
  --url2 https://gitlab.b --token2 $GITLAB_TOKEN_2 \
  --json-prefix reports/relatorio-json \
  --csv-prefix  reports/relatorio-csv
```


## Opções principais
- --url1 / --token1: URL e token do GitLab 1 (ou defina GITLAB_URL_1/GITLAB_TOKEN_1)
- --url2 / --token2: URL e token do GitLab 2 (ou defina GITLAB_URL_2/GITLAB_TOKEN_2)
- --no-verify-ssl: desabilita verificação SSL (use somente quando necessário)

Saídas para arquivos (pelo menos uma é obrigatória):
- --out-json <arquivo>: salva o relatório combinado em JSON
- --out-csv <arquivo>: salva o relatório combinado em CSV
- --json-prefix <prefixo>: gera JSONs separados: <prefixo>_gitlab1.json, <prefixo>_gitlab2.json, <prefixo>_common.json
- --csv-prefix <prefixo>: gera CSVs separados: <prefixo>_gitlab1.csv, <prefixo>_gitlab2.csv, <prefixo>_common.csv

Opções de paginação, logs e resiliência:
- --per-page <n>: tamanho da página (padrão 100, máximo 100)
- --max-retries <n>: número máximo de tentativas em erros transitórios (padrão 5)
- --retry-backoff <fator>: fator de backoff exponencial entre tentativas (padrão 1.5)
- --log-file <arquivo>: registra também em arquivo (além de stderr)


## O que o relatório contém
Cada projeto possui os campos:
- id, name, group (namespace), path (path_with_namespace), web_url, visibility

Relatório combinado (JSON):
- list1: lista de projetos do GitLab 1
- list2: lista de projetos do GitLab 2
- common_by_path: projetos comuns (casados por path), contendo ambos os lados
- summary: contagens (list1, list2, common_by_path)

Relatórios separados:
- <prefix>_gitlab1.json/.csv: todos os projetos do GitLab 1
- <prefix>_gitlab2.json/.csv: todos os projetos do GitLab 2
- <prefix>_common.json/.csv: somente os projetos presentes em ambos (por path)


## Exemplo de estrutura CSV do combinado
Cabeçalho e linhas de listas:
```
SECTION,id,name,group,path,web_url,visibility,origin
LIST,123,proj-a,grupo-a,grupo-a/proj-a,https://... ,private,1
LIST,456,proj-b,grupo-b,grupo-b/proj-b,https://... ,internal,2
```
Seção de comuns por path:
```
COMMON_BY_PATH,id_1,name_1,group_1,path,web_url_1,visibility_1,id_2,name_2,group_2,web_url_2,visibility_2
COMMON_BY_PATH,123,proj-a,grupo-a,grupo-a/proj-a,https://... ,private,999,proj-a,grupo-a,https://... ,private
```


## Paginação, logs e retentativas
- Paginação explícita: o script busca páginas até encontrar uma página vazia. O per_page padrão é 100 (limite da API).
- Logs: cada solicitação de página é logada em stderr e opcionalmente em um arquivo (--log-file). Ex.: “Solicitando página 3 (per_page=100)”, “Página 3 retornou 100 projetos...”.
- Erros transitórios: códigos 429/500/502/503/504 são automaticamente retentados com backoff exponencial (controlado por --max-retries e --retry-backoff).


## Dicas para grandes instâncias (>3000 projetos)
- Mantenha `--per-page 100` (máximo permitido) para melhor desempenho.
- Utilize `--log-file` para registrar o progresso sem poluir o terminal.
- Em janelas de manutenção ou instabilidades, aumente `--max-retries` e/ou `--retry-backoff`.


## SSL e segurança
- Por padrão, a verificação SSL está habilitada. Use `--no-verify-ssl` somente quando necessário (ambientes com certificados não confiáveis).
- Mantenha seus tokens privados seguros; prefira variáveis de ambiente ou um gerenciador de segredos.


## Códigos de saída
- 0: sucesso
- 1: erro inesperado
- 2: erro de autenticação (token inválido, etc.)
- 3: erro retornado pelo GitLab (python-gitlab)


## Solução de problemas
- “python-gitlab is required”: instale as dependências com `pip install -r requirements.txt`.
- “Parâmetros ausentes”: forneça URLs e tokens via parâmetros ou variáveis de ambiente.
- Erros 5xx/429: aumente `--max-retries` e `--retry-backoff`; verifique a saúde das instâncias.
- Muitos projetos mas poucos resultados: verifique permissões associadas aos tokens.


## Licença
Você pode adaptar este script às suas necessidades internas. Caso deseje incluir uma licença formal (ex.: MIT), adicione o arquivo LICENSE ao repositório.
