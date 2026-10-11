"""Offline draft checks. Reference CPU fixture only; not production admission.

Schema checker implements ONLY the keywords used in this folder and rejects
unknown keywords. It is not a complete JSON Schema 2020-12 implementation.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parent
KEYWORDS = {'$schema', 'title', 'type', 'required', 'properties', 'additionalProperties',
            'items', 'minItems', 'maxItems', 'enum', 'const', 'pattern', 'minLength',
            'maxLength', 'minimum', 'maximum'}


class Rejected(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f'{code}: {detail}')


def require(condition, code, detail):
    if not condition:
        raise Rejected(code, detail)


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'E_JSON', f'duplicate key {key}')
        result[key] = value
    return result


def parse(data):
    try:
        return json.loads(data, object_pairs_hook=object_pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, Rejected):
            raise
        raise Rejected('E_JSON', 'invalid JSON or non-finite number') from exc


def read(path, max_bytes=1048576):
    require(not path.is_symlink() and path.is_file(), 'E_PATH', f'not a regular file: {path.name}')
    require(path.stat().st_size <= max_bytes, 'E_LIMIT', f'file too large: {path.name}')
    return path.read_bytes()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def schema_supported(schema):
    require(not set(schema) - KEYWORDS, 'E_SCHEMA_ENGINE', f'unsupported keywords: {set(schema) - KEYWORDS}')
    for child in schema.get('properties', {}).values():
        schema_supported(child)
    if 'items' in schema:
        schema_supported(schema['items'])


def check(value, schema, path='$'):
    types = {
        'object': isinstance(value, dict), 'array': isinstance(value, list),
        'string': isinstance(value, str), 'boolean': type(value) is bool,
        'integer': type(value) is int,
        'number': type(value) in (int, float) and math.isfinite(value), 'null': value is None,
    }
    if 'type' in schema:
        allowed = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        require(any(types[t] for t in allowed), 'E_SCHEMA', f'{path}: wrong type')
    if 'const' in schema:
        require(value == schema['const'], 'E_SCHEMA', f'{path}: wrong constant')
    if 'enum' in schema:
        require(value in schema['enum'], 'E_SCHEMA', f'{path}: value outside allowed list')
    if isinstance(value, dict):
        require(set(schema.get('required', [])) <= set(value), 'E_SCHEMA', f'{path}: missing field')
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False:
            require(not set(value) - set(props), 'E_SCHEMA', f'{path}: unknown field')
        for key in value.keys() & props.keys():
            check(value[key], props[key], f'{path}.{key}')
    if isinstance(value, list):
        require(schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', math.inf),
                'E_SCHEMA', f'{path}: array size')
        for index, item in enumerate(value):
            check(item, schema.get('items', {}), f'{path}[{index}]')
    if isinstance(value, str):
        require(schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', math.inf),
                'E_SCHEMA', f'{path}: string length')
        if 'pattern' in schema:
            require(re.search(schema['pattern'], value) is not None, 'E_SCHEMA', f'{path}: pattern mismatch')
    if type(value) in (int, float):
        require(math.isfinite(value), 'E_SCHEMA', f'{path}: non-finite number')
        require(schema.get('minimum', -math.inf) <= value <= schema.get('maximum', math.inf),
                'E_SCHEMA', f'{path}: numeric range')


def validate_schema(value, name):
    schema = parse(read(ROOT / 'schemas' / f'{name}.schema.json'))
    schema_supported(schema)
    check(value, schema)


def checked_file(root, entry, max_bytes):
    rel = Path(entry['path'])
    require(not rel.is_absolute() and '..' not in rel.parts and '\\' not in entry['path']
            and ':' not in entry['path'], 'E_PATH', 'unsafe relative path')
    current = root
    for part in rel.parts:
        current = current / part
        require(not current.is_symlink(), 'E_PATH', 'symlink not allowed')
    require(current.resolve().is_relative_to(root.resolve()), 'E_PATH', 'path outside package')
    data = read(current, max_bytes)
    require(sha(data) == entry['sha256'], 'E_CHECKSUM', f'{entry["path"]}: sha256 mismatch')
    return parse(data)


def validate_package(path, config):
    raw = read(path)
    package = parse(raw)
    validate_schema(package, 'model-package')
    require(package['purpose'] == 'fixture', 'E_PROTOTYPE_ONLY', 'this checker only executes fixture packages')
    require(package['purpose'] in config['policy']['allowed_purposes'], 'E_POLICY', 'purpose not allowed')
    runtime = package['runtime']
    require(runtime['backend'] == 'reference-linear-score-v1', 'E_BACKEND', 'backend not implemented by fixture checker')
    profiles = [p for p in config['runtime_profiles'] if p['name'] == runtime['profile']]
    require(len(profiles) == 1, 'E_RUNTIME', 'runtime profile missing or ambiguous')
    require(all(profiles[0][k] == runtime[k] for k in ('backend', 'device')), 'E_RUNTIME', 'profile mismatch')
    require(runtime['device'] == 'cpu', 'E_RUNTIME', 'reference fixture is CPU only')
    require(all(package['compatibility'][k] == config['target'][k] for k in ('os', 'arch')),
            'E_COMPATIBILITY', 'declared target mismatch (not a host probe)')
    for stage in ('preprocess', 'postprocess'):
        require(package[stage] in config['policy'][f'allowed_{stage}'], 'E_TRANSFORM', f'{stage} not allowed')
    require(package['preprocess'] == 'tensor-json-v1' and package['postprocess'] == 'normalized-score-v1',
            'E_TRANSFORM', 'transform not implemented')
    expected_io = {'input': {'name': 'IMAGE', 'dtype': 'FP32', 'shape': [1, 1, 2, 2]},
                   'output': {'name': 'SCORE', 'dtype': 'FP32', 'shape': [1]}}
    require(package['io'] == expected_io, 'E_IO', 'fixture requires IMAGE FP32 [1,1,2,2] -> SCORE FP32 [1]')
    for key in ('cpu_millicores', 'ram_mib'):
        require(package['resources'][key] <= config['capacity'][key], 'E_RESOURCE', f'{key} exceeds budget')
    require(package['resources']['peak_vram_mib'] == 0, 'E_RESOURCE', 'CPU fixture must declare zero VRAM')
    require(config['limits']['max_decoded_pixels'] >= 4, 'E_LIMIT', 'fixture requires four values')
    model = checked_file(path.parent, package['artifact'], config['limits']['max_payload_bytes'])
    require(isinstance(model, dict) and set(model) == {'gain', 'bias'}, 'E_ARTIFACT', 'gain/bias only')
    require(all(type(x) in (int, float) and math.isfinite(x) and -4 <= x <= 4 for x in model.values()),
            'E_ARTIFACT', 'gain/bias must be finite numbers in [-4,4]')
    values = checked_file(path.parent, package['golden']['input'], config['limits']['max_payload_bytes'])
    require(isinstance(values, list) and len(values) == 4 and
            all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in values),
            'E_IO', 'golden input requires four finite FP32-compatible values in [0,1]')
    start = time.monotonic()
    for _ in range(package['warmup']['runs']):
        score = min(1.0, max(0.0, model['gain'] * sum(values) / 4 + model['bias']))
    require((time.monotonic() - start) * 1000 <= package['warmup']['timeout_ms'], 'E_WARMUP', 'deadline exceeded')
    golden = package['golden']
    require(abs(score - golden['expected_score']) <= golden['atol'] + golden['rtol'] * abs(golden['expected_score']),
            'E_GOLDEN', 'actual score differs from golden expectation')
    return package, sha(raw), score


def validate_bundle(directory):
    directory = Path(directory)
    config = parse(read(directory / 'site-config.json'))
    validate_schema(config, 'site-config')
    require(config['mode'] == 'lab', 'E_PROTOTYPE_ONLY', 'production admission/signature/runtime checks are not implemented')
    require(not config['policy']['require_signature'], 'E_SIGNATURE', 'signature verification not implemented; cannot accept required signatures')
    profiles = config['runtime_profiles']
    require(len({p['name'] for p in profiles}) == len(profiles), 'E_RUNTIME', 'duplicate runtime profile')
    packages = {}
    for path in sorted((directory / 'packages').glob('*/manifest.json')):
        require(not path.parent.is_symlink(), 'E_PATH', 'package directory symlink')
        p, digest, score = validate_package(path, config)
        key = (p['name'], p['version'])
        require(key not in packages, 'E_DUPLICATE', 'duplicate package name/version')
        packages[key] = (p, digest, score)
    require(packages, 'E_EMPTY', 'no packages')
    for p, _, _ in packages.values():
        for ref in p['rollback_candidates']:
            key = (ref['name'], ref['version'])
            require(key in packages and packages[key][1] == ref['manifest_sha256'],
                    'E_ROLLBACK', 'rollback package absent or digest mismatch')
            require(key != (p['name'], p['version']), 'E_ROLLBACK', 'self rollback forbidden')
    recipes = {}
    results = []
    for path in sorted((directory / 'recipes').glob('*.json')):
        raw = read(path)
        r = parse(raw)
        validate_schema(r, 'recipe')
        require(all(r[k] == config[k] for k in ('site_id', 'station_id')), 'E_SITE', 'recipe site/station mismatch')
        key = (r['name'], r['version'])
        require(key not in recipes, 'E_DUPLICATE', 'duplicate recipe name/version')
        ref = r['package']
        target = packages.get((ref['name'], ref['version']))
        require(target is not None and target[1] == ref['manifest_sha256'], 'E_REFERENCE', 'package missing or digest mismatch')
        recipes[key] = (r, sha(raw))
        results.append({'recipe': r['name'], 'package': ref['name'], 'score': target[2],
                        'decision': 'NG' if target[2] >= r['decision']['threshold'] else 'OK'})
    require(recipes, 'E_EMPTY', 'no recipes')
    for r, _ in recipes.values():
        ref = r['rollback_recipe']
        if ref is None:
            continue
        target = recipes.get((ref['name'], ref['version']))
        require(target is not None and target[1] == ref['sha256'], 'E_ROLLBACK', 'rollback recipe absent or digest mismatch')
        prior_ref = target[0]['package']
        current = packages[(r['package']['name'], r['package']['version'])][0]
        require(prior_ref in current['rollback_candidates'], 'E_ROLLBACK', 'recipe predecessor not allowed by package')
    for origin in recipes:
        seen = set()
        key = origin
        while key is not None:
            require(key not in seen, 'E_ROLLBACK', 'recipe rollback cycle')
            seen.add(key)
            ref = recipes[key][0]['rollback_recipe']
            key = None if ref is None else (ref['name'], ref['version'])
    return {'status': 'PASS', 'scope': 'local reference CPU fixture; no production/GPU deployment',
            'packages': len(packages), 'recipes': len(recipes), 'results': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--examples', type=Path, default=ROOT / 'examples')
    args = parser.parse_args()
    try:
        print(json.dumps(validate_bundle(args.examples), indent=2, ensure_ascii=False))
    except (Rejected, OSError) as exc:
        print(json.dumps({'status': 'REJECTED', 'reason': str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
