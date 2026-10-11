"""Kiem tinh openapi.v1.yaml theo cac quy tac W2-04 (khong can server).

Khong thay the mot OpenAPI validator day du; kiem cac quy tac ma mentor yeu cau:
versioned path, tach plane, auth/RBAC tren moi operation, error schema chung, example hop le,
khong lo API noi bo cua Triton, va dong bo voi route/role cua reference_api.py.
"""
import json
import re
import sys
from pathlib import Path

import jsonschema
import yaml

HERE = Path(__file__).resolve().parent
PORTS = {'inference': {'8443'}, 'management': {'9443'}, 'both': {'8443', '9443'}}
FORBIDDEN_PROPS = {'inputs', 'outputs', 'datatype', 'tensor', 'model_name', 'triton_url', 'shape'}


def walk(node, path='$'):
    yield path, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f'{path}.{k}')
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f'{path}[{i}]')


def resolve(doc, ref):
    cur = doc
    for part in ref[2:].split('/'):
        cur = cur[part]
    return cur


def deref(doc, node):
    while isinstance(node, dict) and '$ref' in node:
        try:
            node = resolve(doc, node['$ref'])
        except (KeyError, TypeError):
            return {}  # da bao o check all_refs_resolve
    return node


def run(spec_path=HERE / 'openapi.v1.yaml', server_module=None, examples_dir=HERE / 'examples'):
    doc = yaml.safe_load(Path(spec_path).read_text(encoding='utf-8'))
    checks = []

    def check(name, ok, detail=''):
        checks.append({'check': name, 'result': 'PASS' if ok else 'FAIL', 'detail': detail})

    check('openapi_3_1', str(doc.get('openapi', '')).startswith('3.1.'), doc.get('openapi'))
    check('info_version_semver', bool(re.fullmatch(r'\d+\.\d+\.\d+(-[\w.]+)?', doc['info']['version'])),
          doc['info']['version'])
    limits = doc['info'].get('x-limits', {})
    need = {'max_body_bytes', 'max_image_bytes', 'queue_capacity', 'queue_timeout_s', 'execution_timeout_s',
            'body_read_timeout_s', 'review_band'}
    check('limits_declared', need <= set(limits), sorted(need - set(limits)))

    bad_refs = []
    for p, node in walk(doc):
        if isinstance(node, dict) and '$ref' in node:
            try:
                resolve(doc, node['$ref'])
            except (KeyError, TypeError):
                bad_refs.append(f"{p}: {node['$ref']}")
    check('all_refs_resolve', not bad_refs, bad_refs[:5])

    ops, op_ids, problems = {}, [], []
    for path, item in doc['paths'].items():
        servers = item.get('servers', doc['servers'])
        ports = {re.search(r':(\d+)$', s['url']).group(1) for s in servers}
        for method, op in item.items():
            if method not in ('get', 'post', 'put', 'patch', 'delete'):
                continue
            oid = op.get('operationId')
            op_ids.append(oid)
            ops[oid] = (method.upper(), path, op)
            plane = op.get('x-plane')
            tag = (op.get('tags') or [None])[0]
            if not path.startswith(('/v1/', '/healthz', '/readyz')):
                problems.append(f'{oid}: path not versioned')
            if plane not in PORTS or ports != PORTS[plane]:
                problems.append(f'{oid}: plane {plane} served on ports {sorted(ports)}')
            if path.startswith('/v1/admin') != (plane == 'management'):
                problems.append(f'{oid}: /v1/admin must equal management plane')
            if plane == 'management' and op.get('x-roles') != ['admin']:
                problems.append(f'{oid}: management op must be admin-only')
            secured = op.get('security', doc.get('security')) not in ([], None)
            if tag == 'health':
                if secured or op.get('x-roles') != ['anonymous']:
                    problems.append(f'{oid}: health must be anonymous')
            else:
                if not secured:
                    problems.append(f'{oid}: missing security')
                if not {'401', '403'} <= set(op['responses']):
                    problems.append(f'{oid}: must document 401 and 403')
                if not set(op.get('x-roles', [])) <= {'viewer', 'operator', 'admin'} or not op.get('x-roles'):
                    problems.append(f'{oid}: invalid x-roles')
            if 'requestBody' in op and not {'400', '415'} <= set(op['responses']):
                problems.append(f'{oid}: body ops must document 400 and 415')
            for status, resp in op['responses'].items():
                r = deref(doc, resp)
                if 'X-Trace-Id' not in r.get('headers', {}):
                    problems.append(f'{oid} {status}: missing X-Trace-Id header')
                if int(status) >= 400:
                    content = r.get('content', {})
                    if oid not in ('getReadiness',) and (
                            list(content) != ['application/problem+json'] or
                            content['application/problem+json']['schema'] != {
                                '$ref': '#/components/schemas/Problem'}):
                        problems.append(f'{oid} {status}: errors must use application/problem+json Problem')
    check('operation_ids_unique', len(op_ids) == len(set(op_ids)) and None not in op_ids, op_ids)
    check('operation_rules', not problems, problems)

    leaks = [p for p in doc['paths'] if '/v2/' in p or 'infer' in p.lower() or 'repository' in p]
    for name, schema in doc['components']['schemas'].items():
        for p, node in walk(schema):
            if isinstance(node, dict) and isinstance(node.get('properties'), dict):
                leaks += [f'{name}{p[1:]}.{k}' for k in node['properties'] if k in FORBIDDEN_PROPS]
    check('no_triton_internal_api_exposed', not leaks, leaks)

    # Examples phai dung schema cua chung
    bad_examples, n_examples = [], 0

    def validate(value, schema, where):
        nonlocal n_examples
        n_examples += 1
        root = {'components': doc['components'], **deref(doc, schema)}
        errs = list(jsonschema.Draft202012Validator(root).iter_errors(value))
        if errs:
            bad_examples.append(f'{where}: {errs[0].message[:120]}')

    for oid, (_, _, op) in ops.items():
        media = [('request', m) for m in op.get('requestBody', {}).get('content', {}).values()]
        for status, resp in op['responses'].items():
            media += [(status, m) for m in deref(doc, resp).get('content', {}).values()]
        for where, m in media:
            if 'example' in m:
                validate(m['example'], m['schema'], f'{oid}/{where}/example')
            for ex_name, ex in m.get('examples', {}).items():
                validate(deref(doc, ex)['value'], m['schema'], f'{oid}/{where}/{ex_name}')
    check('examples_match_schemas', not bad_examples and n_examples >= 10, bad_examples or n_examples)

    # Dong bo voi reference implementation
    if server_module is not None:
        mismatch = []
        for plane, routes in (('inference', server_module.INFERENCE_ROUTES),
                              ('management', server_module.MANAGEMENT_ROUTES)):
            spec_ops = {o for o, (_, _, op) in ops.items() if op['x-plane'] in (plane, 'both')}
            impl_ops = {r[2] for r in routes}
            if spec_ops != impl_ops:
                mismatch.append(f'{plane}: spec-only {sorted(spec_ops - impl_ops)} impl-only {sorted(impl_ops - spec_ops)}')
            for method, _, oid, roles in routes:
                spec_roles = set(ops[oid][2]['x-roles'])
                impl_roles = {'anonymous'} if roles is None else set(roles)
                if spec_roles != impl_roles or ops[oid][0] != method:
                    mismatch.append(f'{oid}: roles/method differ')
        check('spec_matches_reference_routes_and_roles', not mismatch, mismatch)
        src = (HERE / 'reference_api.py').read_text(encoding='utf-8')
        used = set(re.findall(r"ApiError\(\d{3}, '([A-Z_]+)'", src))
        enum = set(doc['components']['schemas']['ErrorCode']['enum'])
        check('error_codes_declared', used <= enum, sorted(used - enum))
        statuses = set(int(s) for s in re.findall(r'ApiError\((\d{3}),', src))
        documented = {int(s) for _, (_, _, op) in ops.items() for s in op['responses']}
        glob = {int(k) for k in doc['info'].get('x-global-responses', {}) if k.isdigit()}
        check('error_statuses_documented_somewhere', statuses <= documented | glob, sorted(statuses - documented))

    if examples_dir is not None and Path(examples_dir).is_dir():
        bad, n = [], 0
        problem = {'$ref': '#/components/schemas/Problem'}
        for f in sorted(Path(examples_dir).glob('[0-9][0-9]-*.json')):
            rec = json.loads(f.read_text(encoding='utf-8'))
            n += 1
            oid, status = rec['operationId'], str(rec['status'])
            if oid is None:
                schema = problem
            else:
                resp = deref(doc, ops[oid][2]['responses'].get(status) or
                             doc['info'].get('x-global-responses', {}).get(status, {}))
                content = resp.get('content', {})
                if not content:
                    bad.append(f'{f.name}: status {status} not documented for {oid}')
                    continue
                schema = next(iter(content.values()))['schema']
                if rec['request_body'] is not None and status in ('200', '202') and 'requestBody' in ops[oid][2]:
                    req_schema = ops[oid][2]['requestBody']['content']['application/json']['schema']
                    errs = list(jsonschema.Draft202012Validator({'components': doc['components'],
                                                                 **deref(doc, req_schema)}).iter_errors(
                        rec['request_body']))
                    if errs:
                        bad.append(f'{f.name} request: {errs[0].message[:100]}')
            errs = list(jsonschema.Draft202012Validator({'components': doc['components'],
                                                         **deref(doc, schema)}).iter_errors(rec['response_body']))
            if errs:
                bad.append(f'{f.name}: {errs[0].message[:100]}')
            if 'Bearer ' in json.dumps(rec) and '<redacted' not in json.dumps(rec['request_headers']):
                bad.append(f'{f.name}: unredacted Authorization')
        check('example_files_match_spec', not bad and n >= 10, bad or n)

    return {'result': 'PASS' if all(c['result'] == 'PASS' for c in checks) else 'FAIL',
            'operations': len(ops), 'examples_validated': n_examples, 'checks': checks}


if __name__ == '__main__':
    sys.path.insert(0, str(HERE))
    import reference_api
    out = run(server_module=reference_api)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out['result'] == 'PASS' else 1)
