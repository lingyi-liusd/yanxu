"""A non-scientific locale preference survives an empty native browser store."""
import unittest
import urllib.error
import urllib.request
import test_server as support


class UIPreferencesTests(unittest.TestCase):
    api=support.ServerCase.api
    _wait_ready=support.ServerCase._wait_ready
    setUp=support.ServerCase.setUp
    tearDown=support.ServerCase.tearDown

    def test_language_persists_without_changing_project_state_or_revision(self):
        before=self.api('/api/state')
        self.assertEqual(self.api('/api/ui/preferences')[2],{'language':None})
        self.assertEqual(self.api('/api/ui/preferences',{'language':'en'})[2],{'language':'en'})
        self.assertEqual(self.api('/api/state'),before)
        with urllib.request.urlopen(self.base+'/',timeout=3) as response:
            self.assertIn("const savedLocale='en'",response.read().decode('utf-8'))
        self.proc.terminate();self.proc.wait(timeout=3)
        import os,subprocess,sys
        env=dict(os.environ,RESEARCH_DESK_DATA_DIR=str(self.data_dir),PORT=str(self.port))
        self.proc=subprocess.Popen([sys.executable,str(support.SERVER)],cwd=str(support.ROOT),env=env,
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self._wait_ready()
        self.assertEqual(self.api('/api/ui/preferences')[2],{'language':'en'})
        self.assertEqual(self.api('/api/state'),before)

    def test_unknown_extra_or_nonstring_preference_cannot_change_other_settings(self):
        for body in ({'language':'<script>'},{'language':None},{'language':'en','enabled':True},{}, {'language':True}):
            self.assertEqual(self.api('/api/ui/preferences',body)[0],400)
        self.assertEqual(self.api('/api/ui/preferences')[2],{'language':None})

    def test_unauthenticated_preference_is_denied(self):
        for data in (None,b'{"language":"en"}'):
            request=urllib.request.Request(self.base+'/api/ui/preferences',data=data,
                                           headers={'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request,timeout=3)
            self.assertEqual(error.exception.code,401)


if __name__=='__main__':unittest.main()
