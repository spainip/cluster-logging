#!/usr/bin/env python3
"""Render pinned charts without loading any credential values."""
import pathlib
import subprocess
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def render(component):
    bundle = ROOT / 'fleet' / component
    config = yaml.safe_load((bundle / 'fleet.yaml').read_text())['helm']
    result = subprocess.run([
        'helm', 'template', config['releaseName'], config['chart'],
        '--repo', config['repo'], '--version', config['version'],
        '--namespace', 'logging', '--kube-version', '1.35.8',
        '-f', str(bundle / 'values.yaml'),
    ], check=True, capture_output=True, text=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def main():
    loki, alloy = render('loki'), render('alloy')
    assert yaml.safe_load((ROOT / 'fleet/loki/fleet.yaml').read_text())['helm']['disablePreProcess'] is True
    av = yaml.safe_load((ROOT / 'fleet/alloy/values.yaml').read_text())
    assert av['alloy']['stabilityLevel'] == 'experimental'
    assert next(e for e in av['alloy']['extraEnv'] if e['name'] == 'LOG_NAMESPACE_FILTER')['value'] == '.+'
    assert len([d for d in loki if d['kind'] == 'StatefulSet']) == 1
    assert len([d for d in alloy if d['kind'] == 'DaemonSet']) == 1
    for doc in loki + alloy:
        assert doc['kind'] not in ('Ingress', 'IngressRoute', 'Secret')
        if doc['kind'] == 'Service':
            assert doc['spec'].get('type', 'ClusterIP') == 'ClusterIP'
        if doc['kind'] in ('Role', 'ClusterRole'):
            assert not any('secrets' in rule.get('resources', []) for rule in doc.get('rules', []))
        if doc['kind'] in ('StatefulSet', 'DaemonSet'):
            for container in doc['spec']['template']['spec']['containers']:
                assert '@sha256:' in container['image']
                for env in container.get('envFrom', []):
                    assert doc['kind'] == 'StatefulSet'
                    assert env['secretRef']['name'] == 'loki-s3'
    config = next(d['data']['config.yaml'] for d in loki if d['kind'] == 'ConfigMap' and 'config.yaml' in d.get('data', {}))
    assert '${AWS_ACCESS_KEY_ID}' in config and '${AWS_SECRET_ACCESS_KEY}' in config
    parsed = yaml.safe_load(config)
    assert parsed['limits_config']['retention_period'] == '336h'
    assert parsed['compactor']['retention_enabled'] is True
    assert parsed['common']['storage']['s3']['bucketnames'] == 'spainip-loki-data'
    assert parsed['ruler']['storage']['s3']['bucketnames'] == 'spainip-loki-rules'
    support = subprocess.run(['kubectl', 'kustomize', str(ROOT / 'fleet' / 'logging-support')], capture_output=True, text=True, check=True)
    for doc in yaml.safe_load_all(support.stdout):
        if doc['kind'] == 'ClusterRole':
            assert doc['rules'] == [{'apiGroups': [''], 'resources': ['pods'], 'verbs': ['get', 'list', 'watch']}]
    print('Pinned charts, credentials, RBAC, storage, exposure and retention checks passed.')


if __name__ == '__main__':
    main()
