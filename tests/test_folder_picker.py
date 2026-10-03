import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import folder_picker
import test_server as support
import urllib.request
import urllib.error


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.helper=pathlib.Path(self.tmp.name)/'picker'
        self.helper.touch()
        self.addCleanup(patch.stopall)
        patch('folder_picker.sys.platform','darwin').start()
        patch.dict('os.environ',{'RESEARCH_DESK_FOLDER_PICKER':str(self.helper)}).start()

    def response(self,value):
        return patch('folder_picker.subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps(value),''))

    def test_pick_and_cancel_do_not_traverse_or_grant(self):
        with self.response({'path':'/synthetic/资料','cancelled':False}) as run:
            self.assertEqual(folder_picker.choose()['path'],'/synthetic/资料')
            self.assertEqual(run.call_args.args[0],[str(self.helper)])
        with self.response({'cancelled':True}):
            self.assertEqual(folder_picker.choose(),{'cancelled':True})

    def test_invalid_timeout_and_busy_release_lock(self):
        for value in ({'path':'relative'},{'path':'/line\nbreak'},{'path':12}):
            with self.response(value),self.assertRaises(ValueError):folder_picker.choose()
        with patch('folder_picker.subprocess.run',side_effect=subprocess.TimeoutExpired([],180)),self.assertRaises(ValueError):folder_picker.choose()
        self.assertTrue(folder_picker._LOCK.acquire(False))
        try:
            with self.assertRaises(ValueError):folder_picker.choose()
        finally:folder_picker._LOCK.release()
        with self.response({'cancelled':True}):self.assertEqual(folder_picker.choose(),{'cancelled':True})

    def test_unavailable_and_symlink_are_not_executed(self):
        self.helper.unlink()
        with self.assertRaises(ValueError):folder_picker.choose()
        self.helper.symlink_to('/usr/bin/true')
        with self.assertRaises(ValueError):folder_picker.choose()


class PickerHTTPTests(unittest.TestCase):
    setUp=support.ServerCase.setUp
    tearDown=support.ServerCase.tearDown
    api=support.ServerCase.api
    _wait_ready=support.ServerCase._wait_ready
    create_project=support.ServerCase.create_project
    def test_human_same_origin_strict_body_and_project(self):
        self.create_project()
        def request(body,origin=None,token=None):
            headers={'Authorization':'Bearer '+(token or self.token),'Content-Type':'application/json'}
            if origin:headers['Origin']=origin
            req=urllib.request.Request(self.base+'/api/project/folder-picker',data=json.dumps(body).encode(),headers=headers)
            try:
                with urllib.request.urlopen(req,timeout=3) as r:return r.status,json.loads(r.read())
            except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
        self.assertEqual(request({'project_id':'p1'})[0],403)
        self.assertEqual(request({'project_id':'p1'},'https://evil.example')[0],403)
        self.assertEqual(request({'project_id':'p1'},self.base,'agent-token')[0],401)
        self.assertEqual(request({'project_id':'p1','command':'anything'},self.base)[0],400)
        self.assertEqual(request({'project_id':'unknown'},self.base)[0],400)
        self.assertFalse(self.api('/api/project/workspace?project_id=p1')[2]['configured'])
        self.assertFalse(self.api('/api/project/manager?project_id=p1')[2]['source_bridge']['enabled'])


if __name__=='__main__':unittest.main()
