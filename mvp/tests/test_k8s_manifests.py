"""W4-03: cac rang buoc thiet ke cua manifests Kubernetes (kiem tinh, khong can cluster)."""
import json
import re
import unittest
from pathlib import Path

import yaml

K8S = Path(__file__).resolve().parent.parent / 'deploy' / 'k8s'


def docs(name):
    return [d for d in yaml.safe_load_all((K8S / 'base' / name).read_text(encoding='utf-8')) if d]


class TestManifests(unittest.TestCase):
    def setUp(self):
        self.dep = docs('deployment.yaml')[0]
        self.pod = self.dep['spec']['template']['spec']
        self.c = {c['name']: c for c in self.pod['containers']}

    def test_single_writer_and_history(self):
        self.assertEqual((self.dep['spec']['replicas'], self.dep['spec']['strategy']['type']), (1, 'Recreate'))
        self.assertGreaterEqual(self.dep['spec']['revisionHistoryLimit'], 2)  # can cho rollout undo

    def test_triton_is_reachable_only_inside_the_pod(self):
        self.assertIn('--http-address=127.0.0.1', self.c['triton']['args'])
        self.assertIn('--model-control-mode=explicit', self.c['triton']['args'])
        self.assertNotIn(8000, [p['containerPort'] for p in self.c['triton'].get('ports', [])])
        for svc in docs('services.yaml'):
            for p in svc['spec']['ports']:
                self.assertNotIn(p.get('targetPort'), (8000, 'http'), svc['metadata']['name'])
                self.assertNotEqual(p['port'], 8000)
        self.assertIn('--kserve-url=http://127.0.0.1:8000', self.c['api']['args'])

    def test_probes_use_readyz_for_readiness_and_healthz_for_liveness(self):
        api = self.c['api']
        self.assertEqual(api['readinessProbe']['httpGet']['path'], '/readyz')
        self.assertEqual(api['startupProbe']['httpGet']['path'], '/readyz')
        self.assertEqual(api['livenessProbe']['httpGet']['path'], '/healthz')
        self.assertGreaterEqual(api['startupProbe']['failureThreshold'] * api['startupProbe']['periodSeconds'], 120)
        for name in ('readinessProbe', 'livenessProbe', 'startupProbe'):
            self.assertIn(name, self.c['triton'])

    def test_resources_and_security_context(self):
        for c in self.c.values():
            self.assertIn('requests', c['resources'])
            self.assertIn('limits', c['resources'])
            self.assertFalse(c['securityContext']['allowPrivilegeEscalation'])
        sc = self.c['api']['securityContext']
        self.assertTrue(sc['runAsNonRoot'] and sc['readOnlyRootFilesystem'])
        self.assertEqual(sc['capabilities']['drop'], ['ALL'])
        self.assertFalse(self.pod['automountServiceAccountToken'])

    def test_data_survives_pod_and_namespace_deletion(self):
        vol = {v['name']: v for v in self.pod['volumes']}
        self.assertEqual(vol['run']['persistentVolumeClaim']['claimName'], 'vr01-run')
        self.assertNotIn('hostPath', json.dumps(self.pod))  # hostPath truc tiep trong pod bi PodSecurity baseline chan
        pv, pvc = docs('storage.yaml')
        self.assertEqual((pv['spec']['hostPath']['path'], pv['spec']['persistentVolumeReclaimPolicy']),
                         ('/var/lib/vr01/run', 'Retain'))
        self.assertEqual(pvc['spec']['volumeName'], pv['metadata']['name'])
        self.assertEqual(docs('namespace.yaml')[0]['metadata']['labels']['pod-security.kubernetes.io/enforce'], 'baseline')
        triton_mount = self.c['triton']['volumeMounts'][0]
        self.assertTrue(triton_mount['readOnly'])
        self.assertEqual(triton_mount['subPath'], 'triton-repo')

    def test_network_policy_only_opens_business_ports_to_everyone(self):
        np = docs('networkpolicy.yaml')[0]
        open_ports = [p['port'] for rule in np['spec']['ingress'] if 'from' not in rule for p in rule['ports']]
        self.assertEqual(sorted(open_ports), [8443, 9443])
        restricted = [p['port'] for rule in np['spec']['ingress'] if 'from' in rule for p in rule['ports']]
        self.assertEqual(sorted(restricted), [8002, 9090])

    def test_offline_gpu_overlay_is_offline_cpu_plus_the_gpu_patches(self):
        cpu = yaml.safe_load((K8S / 'overlays' / 'offline-cpu' / 'kustomization.yaml').read_text())
        gpu = yaml.safe_load((K8S / 'overlays' / 'offline-gpu' / 'kustomization.yaml').read_text())
        lab = yaml.safe_load((K8S / 'overlays' / 'lab-gpu' / 'kustomization.yaml').read_text())
        self.assertEqual(gpu['images'], cpu['images'])                      # cung image local, khong keo registry
        ops = lambda k: yaml.safe_load(k['patches'][0]['patch'])            # noqa: E731
        self.assertEqual(ops(gpu), ops(cpu) + ops(lab))                     # Never-pull + KIND_GPU + 1 GPU

    def test_overlays_pin_the_same_triton_digest_as_compose(self):
        env = (K8S.parent / '.env.sample').read_text()
        digest = re.search(r'TRITON_IMAGE=.*@(sha256:[a-f0-9]{64})', env).group(1)
        for overlay in ('lab-cpu', 'lab-gpu'):
            k = yaml.safe_load((K8S / 'overlays' / overlay / 'kustomization.yaml').read_text())
            tri = next(i for i in k['images'] if i['name'] == 'tritonserver')
            self.assertEqual(tri['digest'], digest, overlay)
        self.assertIn(digest, (K8S / 'load-images.sh').read_text())


if __name__ == '__main__':
    unittest.main()
