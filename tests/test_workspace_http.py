import pathlib
import tempfile
import unittest
import test_server as support


class WorkspaceHTTPTests(unittest.TestCase):
    api=support.ServerCase.api
    _wait_ready=support.ServerCase._wait_ready
    create_project=support.ServerCase.create_project
    tearDown=support.ServerCase.tearDown

    def setUp(self):
        support.ServerCase.setUp(self)
        self.files_tmp=tempfile.TemporaryDirectory(prefix='workspace-http-')
        self.addCleanup(self.files_tmp.cleanup)
        self.root=pathlib.Path(self.files_tmp.name).resolve()
        (self.root/'alpha').mkdir();(self.root/'beta').mkdir()
        self.create_project('a','项目A');self.create_project('b','项目B')

    def binding(self, project='a', relative='alpha', revision=0, **extra):
        return dict(project_id=project,root=str(self.root),relative_path=relative,if_revision=revision,
                    consent='project-workspace-binding-v1',**extra)

    def test_dry_binding_does_not_read_or_modify_original_project(self):
        before=self.api('/api/state')[2]
        self.assertFalse(self.api('/api/project/workspace?project_id=a')[2]['configured'])
        self.assertEqual(self.api('/api/project/workspace',self.binding(dry=True))[0],200)
        self.assertFalse(self.api('/api/project/workspace?project_id=a')[2]['configured'])
        code,_,bound=self.api('/api/project/workspace',self.binding())
        self.assertEqual(code,200,bound);self.assertEqual(bound['state'],'ready')
        self.assertEqual(self.api('/api/state')[2],before)
        manager=self.api('/api/project/manager?project_id=a')[2]
        self.assertFalse(manager['source_bridge']['enabled']);self.assertEqual(manager['used_today'],0)
        self.assertEqual(self.api('/api/project/source-index?project_id=a')[2]['items'],[])

    def test_cross_project_escape_old_revision_and_nonhuman_token_rejected(self):
        self.assertEqual(self.api('/api/project/workspace',self.binding())[0],200)
        self.assertEqual(self.api('/api/project/workspace',self.binding('b','alpha'))[0],400)
        self.assertEqual(self.api('/api/project/workspace',self.binding('b','beta'))[0],200)
        self.assertEqual(self.api('/api/project/workspace',self.binding())[0],400)
        original_token=self.token
        try:
            self.token='not-the-human-token'
            self.assertEqual(self.api('/api/project/workspace',self.binding(revision=1))[0],401)
        finally:
            self.token=original_token
        common=dict(project_id='a',enabled=True,send_content=False,threads=[],if_revision=0,
                    consent='selected-local-sources-v1',workspace_revision=1)
        self.assertEqual(self.api('/api/project/manager/sources',dict(common,folders=[str(self.root/'beta')]))[0],400)
        self.assertEqual(self.api('/api/project/manager/sources',dict(common,folders=[str(self.root/'alpha')],workspace_revision=0))[0],400)
        self.assertEqual(self.api('/api/project/manager/sources',dict(common,folders=[str(self.root/'alpha')]))[0],200)
        self.assertEqual(self.api('/api/project/workspace',self.binding(revision=1,exclusions=['private']))[0],200)
        manager=self.api('/api/project/manager?project_id=a')[2]
        self.assertTrue(manager['source_bridge']['workspace_blocked'])

    def test_rebind_with_old_runtime_consent_keeps_status_readable_without_execution(self):
        self.assertEqual(self.api('/api/project/workspace',self.binding())[0],200)
        runtime=dict(project_id='a',enabled=True,workspace_revision=1,consent='registered-file-metadata-and-review-v1')
        self.assertEqual(self.api('/api/project/manager/runtime',runtime)[0],200)
        self.assertEqual(self.api('/api/project/workspace',self.binding(revision=1,exclusions=['private']))[0],200)
        code,_,manager=self.api('/api/project/manager?project_id=a')
        self.assertEqual(code,200,manager)
        self.assertEqual(manager['workspace']['revision'],2)
        self.assertEqual(manager['workspace']['state'],'ready')
        self.assertTrue(manager['runtime']['enabled'],'Keep the original consent record, not an implicit rewrite')
        self.assertTrue(manager['runtime']['scope_blocked'])
        self.assertFalse(manager['runtime']['effective_enabled'])
        self.assertFalse(manager['file_observations'])
        self.assertEqual(manager['used_today'],0)
        self.assertFalse(any(p['ready'] for p in manager['handoffs']))
        self.assertEqual(self.api('/api/project/context?project_id=a')[0],200)
        sources=dict(project_id='a',enabled=True,send_content=False,threads=[],if_revision=0,
            workspace_revision=2,consent='selected-local-sources-v1',folders=[str(self.root/'alpha')])
        self.assertEqual(self.api('/api/project/manager/sources',sources)[0],200)
        self.assertTrue(self.api('/api/project/manager?project_id=a')[2]['runtime']['scope_blocked'])


if __name__=='__main__': unittest.main()
