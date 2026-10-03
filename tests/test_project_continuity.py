import copy
import json
import pathlib
import sys
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from project_continuity import build, source_watch


class ContinuityTests(unittest.TestCase):
    def baseline(self, source):
        return {'id': 9, 'input': json.dumps(source), 'signature': 'old', 'finished': 123}

    def test_no_baseline_not_fake_new_changes(self):
        self.assertEqual(build({'tasks':[{'id':'a'}]}, 'new')['changes'], [])

    def test_null_field_and_absent_field_are_distinct(self):
        c = build({'tasks':[{'id':'a','note':None}]}, 'new', self.baseline({'tasks':[{'id':'a'}]}))
        self.assertEqual(c['changes'][0]['fields'], ['note'])

    def test_exact_delta_and_order_independence(self):
        old = {'tasks':[{'id':'a','status':'待开始'}, {'id':'b','title':'旧'}]}
        new = {'tasks':[{'id':'c','title':'新'}, {'id':'a','status':'进行中'}]}
        original = copy.deepcopy(new)
        c = build(new, 'new', self.baseline(old))
        self.assertEqual([(r['id'],r['kind']) for r in c['changes']], [('a','updated'),('b','removed'),('c','added')])
        self.assertEqual(c['changes'][0]['fields'], ['status'])
        self.assertEqual(c['changes'][1]['before']['title'], '旧')
        self.assertEqual(new, original)
        self.assertEqual(build(old, 'same', self.baseline({'tasks':list(reversed(old['tasks']))}))['changes'], [])

    def test_delivery_not_verification_and_explicit_negative_only(self):
        source = {'actions':[{'id':'a','status':'finished'}, {'id':'b','status':'running'}],
                  'results':[{'id':'r','outcome':'failure','verification_status':'UNVERIFIED','source_version':'v1'},
                             {'id':'s','outcome':'success','verification_status':'UNVERIFIED','summary':'failure word'},
                             {'id':'t','outcome':'success','verification_status':'VERIFIED'}]}
        c = build(source, 'hash')
        self.assertEqual([r['id'] for r in c['negative_results']], ['r'])
        self.assertEqual([r['id'] for r in c['unverified_results']], ['r','s'])
        self.assertEqual([r['id'] for r in c['active_actions']], ['b'])
        self.assertEqual(c['negative_results'][0]['source_version'], 'v1')

    def test_removed_negative_retains_baseline_source(self):
        r = {'id':'r','outcome':'failure','source_ref':'test','source_version':'sha256:x'}
        c = build({'results':[]}, 'new', self.baseline({'results':[r]}))
        self.assertEqual(c['changes'][0]['before'], r)
        self.assertEqual(c['negative_results'], [])

    def test_file_delta_by_path_and_pending_authority(self):
        old = {'file_observations':[{'path':'/p','observed_version':'v1'}]}
        new = {'file_observations':[{'path':'/p','observed_version':'v2'}],
               'decisions':[{'id':'d','status':'pending'}, {'id':'e','status':'approved'}]}
        c = build(new, 'new', self.baseline(old))
        self.assertEqual([r['id'] for r in c['pending_decisions']], ['d'])
        f = next(r for r in c['changes'] if r['section']=='file_observations')
        self.assertEqual(f['fields'], ['observed_version'])
        self.assertEqual(f['before']['observed_version'], 'v1')

    def test_direct_source_version_impact_no_scientific_mutation(self):
        source = {'file_observations':[{'path':'/scope/status.json','state':'present',
                   'observed_version':'sha256:'+'b'*64,'matches_registered':False}],
                  'results':[{'id':'r','source_ref':'/scope/status.json','source_version':'a'*64,
                              'outcome':'partial','verification_status':'UNVERIFIED'}],
                  'artifacts':[{'id':'a','reference':'/scope/status.json','source_version':'b'*64}]}
        original = copy.deepcopy(source)
        watch = source_watch(source)
        self.assertEqual([r['version_status'] for r in watch[0]['linked_records']], ['VERSION_CHANGED','MATCH'])
        self.assertEqual(watch[0]['review_record_count'], 1)
        self.assertEqual(source, original)
        self.assertEqual(watch[0]['linked_records'][0]['verification_status'], 'UNVERIFIED')

    def test_no_filename_substring_or_action_dependency_guess(self):
        source = {'file_observations':[{'path':'/scope/status.json','state':'missing'}],
                  'results':[{'id':'r','source_ref':'/other/status.json','action_id':'a'},
                             {'id':'q','source_ref':'/scope/status.json.backup','action_id':'a'}]}
        self.assertEqual(source_watch(source)[0]['linked_records'], [])

    def test_labels_and_missing_files_unknown_not_false_version_change(self):
        source = {'file_observations':[{'path':'/scope/a','state':'present','matches_registered':True,
                   'observed_version':'sha256:'+'a'*64}],
                  'evidence':[{'id':'e','source_ref':'/scope/a','source_version':'v1'}]}
        self.assertEqual(source_watch(source)[0]['linked_records'][0]['version_status'], 'UNKNOWN')
        # A retained old hash must not make a now-missing/excluded file comparable.
        source['evidence'][0]['source_version']='a'*64
        for state in ('missing','excluded','unstable','inaccessible_or_symlink'):
            source['file_observations'][0]={'path':'/scope/a','state':state,'observed_version':'sha256:'+'a'*64}
            self.assertEqual(source_watch(source)[0]['linked_records'][0]['version_status'], 'UNKNOWN')
        source['file_observations'][0]={'path':'/scope/a','state':'present','matches_registered':True,'observed_version':'sha256:'+'a'*64}
        source['evidence'][0]['source_version']='a'*64
        self.assertEqual(source_watch(source), [])
        source['file_observations'][0]={'path':'/scope/a','state':'missing'}
        self.assertEqual(source_watch(source)[0]['linked_records'][0]['version_status'], 'UNKNOWN')
