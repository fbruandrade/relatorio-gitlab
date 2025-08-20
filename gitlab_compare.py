#!/usr/bin/env python3
"""
GitLab repositories lister and comparer for two instances.

Requires: python-gitlab (pip install python-gitlab)

Usage examples:
  # Save combined report to JSON file (with pagination logs to stderr)
  python gitlab_compare.py \
    --url1 https://gitlab.company-a.com --token1 $GITLAB_TOKEN_A \
    --url2 https://gitlab.company-b.com --token2 $GITLAB_TOKEN_B \
    --out-json reports/combined.json

  # Save combined report to CSV file with custom pagination and retry settings, logging to a file
  python gitlab_compare.py \
    --url1 https://gitlab.company-a.com --token1 $GITLAB_TOKEN_A \
    --url2 https://gitlab.company-b.com --token2 $GITLAB_TOKEN_B \
    --per-page 100 --max-retries 6 --retry-backoff 2.0 \
    --log-file reports/fetch.log \
    --out-csv reports/combined.csv

  # Generate separate files for each GitLab and for the common projects
  python gitlab_compare.py \
    --url1 https://gitlab.a --token1 $GITLAB_TOKEN_A \
    --url2 https://gitlab.b --token2 $GITLAB_TOKEN_B \
    --json-prefix reports/relatorio \
    --csv-prefix reports/relatorio

  python gitlab_compare.py --help

Outputs are only written to files:
- Combined report (choose one): --out-json <file> or --out-csv <file>
- Separate per-GitLab files (optional, via prefixes):
  - <prefix>_gitlab1.json/.csv: all projects from GitLab 1
  - <prefix>_gitlab2.json/.csv: all projects from GitLab 2
  - <prefix>_common.json/.csv: projects present in both GitLabs (matched by path)

Pagination & resilience:
- The tool explicitly paginates through all projects (default per-page=100), logs each page, and retries transient errors (500/502/503/504/429) with exponential backoff.

Each project entry includes: name, group (namespace), path (path_with_namespace), web_url, id, visibility
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Dict, Iterable, List, Tuple, Optional
import time
from datetime import datetime
import urllib3

try:
    import gitlab  # type: ignore
except Exception as e:
    print("Error: python-gitlab is required. Install with: pip install python-gitlab", file=sys.stderr)
    raise


def connect(url: str, token: str, verify_ssl: bool = True) -> "gitlab.Gitlab":
    gl = gitlab.Gitlab(url=url, private_token=token, ssl_verify=verify_ssl, per_page=100)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    # Validate connection
    gl.auth()  # will raise if token invalid
    return gl


# Nota: a paginação explícita é implementada em fetch_projects com logs e retentativas.


def normalize_project(p) -> Dict[str, str]:
    # Namespace/group extraction: try namespace.full_path then name
    namespace = None
    try:
        ns = getattr(p, 'namespace', None) or {}
        namespace = ns.get('full_path') or ns.get('name') or ns.get('path')
    except Exception:
        namespace = None

    path = getattr(p, 'path_with_namespace', None) or getattr(p, 'path', None)
    name = getattr(p, 'name', None) or (path.split('/')[-1] if isinstance(path, str) else None)
    web_url = getattr(p, 'web_url', None)
    visibility = getattr(p, 'visibility', None)
    pid = getattr(p, 'id', None)

    return {
        'id': str(pid) if pid is not None else '',
        'name': name or '',
        'group': namespace or '',
        'path': path or '',
        'web_url': web_url or '',
        'visibility': visibility or '',
    }


class _Logger:
    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file
        if self.log_file:
            dir_name = os.path.dirname(self.log_file)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

    def log(self, msg: str) -> None:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"[{timestamp}] {msg}\n"
        # stderr for immediate feedback
        try:
            sys.stderr.write(line)
            sys.stderr.flush()
        except Exception:
            pass
        # optional file
        if self.log_file:
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(line)
            except Exception:
                pass


def fetch_projects(url: str, token: str, verify_ssl: bool,
                   per_page: int = 100,
                   max_retries: int = 5,
                   retry_backoff: float = 1.5,
                   logger: Optional[_Logger] = None) -> List[Dict[str, str]]:
    gl = connect(url, token, verify_ssl)
    projects: List[Dict[str, str]] = []

    # Cap per_page to 100 (GitLab API maximum)
    if per_page > 100:
        per_page = 100
    if per_page <= 0:
        per_page = 100

    page = 1
    total = 0
    while True:
        attempt = 0
        while True:
            try:
                if logger:
                    logger.log(f"Solicitando página {page} (per_page={per_page})")
                page_items = gl.projects.list(page=page, per_page=per_page)
                break
            except Exception as e:
                # Try to inspect python-gitlab error codes
                response_code = getattr(e, 'response_code', None)
                transient = response_code in {429, 500, 502, 503, 504}
                if not transient or attempt >= max_retries:
                    if logger:
                        logger.log(f"Falha ao obter página {page}: {e} (código={response_code}). Não será tentado novamente.")
                    raise
                attempt += 1
                sleep_for = retry_backoff ** attempt
                if logger:
                    logger.log(f"Erro transitório (código={response_code}) ao obter página {page}. Tentativa {attempt}/{max_retries}. Aguardando {sleep_for:.1f}s...")
                time.sleep(sleep_for)

        if not page_items:
            if logger:
                logger.log(f"Página {page} vazia. Concluído. Total de projetos: {total}")
            break

        normalized = [normalize_project(p) for p in page_items]
        projects.extend(normalized)
        total += len(normalized)
        if logger:
            logger.log(f"Página {page} retornou {len(normalized)} projetos. Acumulado: {total}")
        page += 1

    return projects


def compare_by_path(list1: List[Dict[str, str]], list2: List[Dict[str, str]]) -> List[Tuple[Dict[str, str], Dict[str, str]]]:
    index2 = {p['path']: p for p in list2 if p.get('path')}
    commons = []
    for p1 in list1:
        path = p1.get('path')
        if path and path in index2:
            commons.append((p1, index2[path]))
    return commons


def build_combined_json(list1, list2, commons):
    return {
        'list1': list1,
        'list2': list2,
        'common_by_path': [
            {
                'path': a['path'],
                'gitlab1': a,
                'gitlab2': b,
            }
            for (a, b) in commons
        ],
        'summary': {
            'count_list1': len(list1),
            'count_list2': len(list2),
            'count_common_by_path': len(commons),
        }
    }


def write_output_json_to_file(filepath: str, list1, list2, commons) -> None:
    payload = build_combined_json(list1, list2, commons)
    dir_name = os.path.dirname(filepath)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_output_csv_to_file(filepath: str, list1, list2, commons) -> None:
    dir_name = os.path.dirname(filepath)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8', newline='') as out_stream:
        writer = csv.writer(out_stream)
        writer.writerow(["SECTION", "id", "name", "group", "path", "web_url", "visibility", "origin"])  # origin: 1 or 2
        for p in list1:
            writer.writerow(["LIST", p['id'], p['name'], p['group'], p['path'], p['web_url'], p['visibility'], "1"]) 
        for p in list2:
            writer.writerow(["LIST", p['id'], p['name'], p['group'], p['path'], p['web_url'], p['visibility'], "2"]) 
        writer.writerow([])
        writer.writerow(["COMMON_BY_PATH", "id_1", "name_1", "group_1", "path", "web_url_1", "visibility_1", "id_2", "name_2", "group_2", "web_url_2", "visibility_2"]) 
        for a, b in commons:
            writer.writerow(["COMMON_BY_PATH", a['id'], a['name'], a['group'], a['path'], a['web_url'], a['visibility'], b['id'], b['name'], b['group'], b['web_url'], b['visibility']])


def _ensure_prefix_dir(prefix: str) -> None:
    dir_name = os.path.dirname(prefix)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)


def write_separate_json(prefix: str, list1, list2, commons) -> None:
    _ensure_prefix_dir(prefix)
    with open(f"{prefix}_gitlab1.json", "w", encoding="utf-8") as f:
        json.dump(list1, f, ensure_ascii=False, indent=2)
    with open(f"{prefix}_gitlab2.json", "w", encoding="utf-8") as f:
        json.dump(list2, f, ensure_ascii=False, indent=2)
    # For commons, output an array of objects with gitlab1/gitlab2 and path
    commons_payload = [
        {"path": a.get("path", ""), "gitlab1": a, "gitlab2": b}
        for (a, b) in commons
    ]
    with open(f"{prefix}_common.json", "w", encoding="utf-8") as f:
        json.dump(commons_payload, f, ensure_ascii=False, indent=2)


essential_fields = ["id", "name", "group", "path", "web_url", "visibility"]


def write_separate_csv(prefix: str, list1, list2, commons) -> None:
    _ensure_prefix_dir(prefix)
    # GitLab 1 list
    with open(f"{prefix}_gitlab1.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(essential_fields)
        for p in list1:
            writer.writerow([p.get(k, "") for k in essential_fields])
    # GitLab 2 list
    with open(f"{prefix}_gitlab2.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(essential_fields)
        for p in list2:
            writer.writerow([p.get(k, "") for k in essential_fields])
    # Commons
    with open(f"{prefix}_common.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["path"] + [f"1_{k}" for k in essential_fields] + [f"2_{k}" for k in essential_fields])
        for a, b in commons:
            writer.writerow([
                a.get("path", ""),
                a.get("id", ""), a.get("name", ""), a.get("group", ""), a.get("path", ""), a.get("web_url", ""), a.get("visibility", ""),
                b.get("id", ""), b.get("name", ""), b.get("group", ""), b.get("path", ""), b.get("web_url", ""), b.get("visibility", ""),
            ])


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lista e compara projetos entre dois GitLabs usando python-gitlab")
    parser.add_argument('--url1', required=False, default=os.getenv('GITLAB_URL_1'), help='URL do GitLab 1 (ou defina GITLAB_URL_1)')
    parser.add_argument('--token1', required=False, default=os.getenv('GITLAB_TOKEN_1'), help='Token privado para GitLab 1 (ou defina GITLAB_TOKEN_1)')
    parser.add_argument('--url2', required=False, default=os.getenv('GITLAB_URL_2'), help='URL do GitLab 2 (ou defina GITLAB_URL_2)')
    parser.add_argument('--token2', required=False, default=os.getenv('GITLAB_TOKEN_2'), help='Token privado para GitLab 2 (ou defina GITLAB_TOKEN_2)')
    parser.add_argument('--no-verify-ssl', action='store_true', help='Desabilita verificação SSL (use com cautela)')
    # Pagination & resilience options
    parser.add_argument('--per-page', type=int, default=100, help='Tamanho da página nas listagens (máximo 100)')
    parser.add_argument('--max-retries', type=int, default=5, help='Número máximo de tentativas para erros 5xx/429')
    parser.add_argument('--retry-backoff', type=float, default=1.5, help='Fator de backoff exponencial entre tentativas')
    parser.add_argument('--log-file', required=False, help='Arquivo de log para registrar paginação e tentativas (stderr por padrão)')
    # Combined report file outputs (choose one)
    parser.add_argument('--out-json', required=False, help='Arquivo para salvar o relatório combinado em JSON')
    parser.add_argument('--out-csv', required=False, help='Arquivo para salvar o relatório combinado em CSV')
    # Separate per-GitLab outputs
    parser.add_argument('--json-prefix', required=False, help='Se definido, gera arquivos JSON separados: <prefix>_gitlab1.json, <prefix>_gitlab2.json, <prefix>_common.json')
    parser.add_argument('--csv-prefix', required=False, help='Se definido, gera arquivos CSV separados: <prefix>_gitlab1.csv, <prefix>_gitlab2.csv, <prefix>_common.csv')

    args = parser.parse_args(argv)

    missing = []
    if not args.url1: missing.append('url1 or GITLAB_URL_1')
    if not args.token1: missing.append('token1 or GITLAB_TOKEN_1')
    if not args.url2: missing.append('url2 or GITLAB_URL_2')
    if not args.token2: missing.append('token2 or GITLAB_TOKEN_2')
    if missing:
        parser.error('Parâmetros ausentes: ' + ', '.join(missing))

    # Validate output options: all outputs must go to files
    if args.out_json and args.out_csv:
        parser.error('Use apenas um dos parâmetros: --out-json ou --out-csv (são mutuamente exclusivos).')
    if not (args.out_json or args.out_csv or args.json_prefix or args.csv_prefix):
        parser.error('Defina pelo menos um destino de arquivo: --out-json, --out-csv, --json-prefix e/ou --csv-prefix.')

    return args


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    verify_ssl = not args.no_verify_ssl

    logger = _Logger(args.log_file)

    try:
        list1 = fetch_projects(
            args.url1, args.token1, verify_ssl,
            per_page=args.per_page, max_retries=args.max_retries,
            retry_backoff=args.retry_backoff, logger=logger,
        )
        list2 = fetch_projects(
            args.url2, args.token2, verify_ssl,
            per_page=args.per_page, max_retries=args.max_retries,
            retry_backoff=args.retry_backoff, logger=logger,
        )
    except gitlab.GitlabAuthenticationError as e:  # type: ignore
        print(f"Erro de autenticação: {e}", file=sys.stderr)
        return 2
    except gitlab.GitlabError as e:  # type: ignore
        print(f"Erro do GitLab: {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"Erro inesperado: {e}", file=sys.stderr)
        return 1

    commons = compare_by_path(list1, list2)

    # Combined report outputs to files (no stdout data)
    if getattr(args, 'out_json', None):
        write_output_json_to_file(args.out_json, list1, list2, commons)
    if getattr(args, 'out_csv', None):
        write_output_csv_to_file(args.out_csv, list1, list2, commons)

    # Optionally generate separate files per GitLab and the common set
    if getattr(args, 'json_prefix', None):
        write_separate_json(args.json_prefix, list1, list2, commons)
    if getattr(args, 'csv_prefix', None):
        write_separate_csv(args.csv_prefix, list1, list2, commons)

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
