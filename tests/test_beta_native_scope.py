"""No login/network: native menu profile forwarding and shell-safe launch."""
import importlib.util
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('native_scope_boot',ROOT/'packaging/beta_boot.py')
boot=importlib.util.module_from_spec(spec);spec.loader.exec_module(boot)


class NativeScopeTests(unittest.TestCase):
    def test_background_preference_is_opt_in_and_private_to_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            a=Path(temp)/'a';b=Path(temp)/'b';a.mkdir();b.mkdir()
            self.assertFalse(boot.background_setting(a)['keep_running_after_window_close'])
            self.assertFalse((a/'native-lifecycle.json').exists())
            self.assertTrue(boot.background_setting(a,True)['keep_running_after_window_close'])
            self.assertFalse(boot.background_setting(b)['keep_running_after_window_close'])
            self.assertTrue(boot.background_setting(a)['keep_running_after_window_close'])
            self.assertFalse(boot.background_setting(a,False)['keep_running_after_window_close'])
            if os.name!='nt':self.assertEqual((a/'native-lifecycle.json').stat().st_mode & 0o777,0o600)

    def test_background_preference_rejects_symlink_and_invalid_value(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp);target=data/'native-lifecycle.json';outside=data/'outside.json'
            outside.write_text('{"keep_running_after_window_close":false}')
            target.symlink_to(outside)
            with self.assertRaises(RuntimeError):boot.background_setting(data,True)
            self.assertIn('false',outside.read_text())
            target.unlink();target.write_text('{"keep_running_after_window_close":"true"}')
            with self.assertRaises(RuntimeError):boot.background_setting(data)

    def test_background_cli_saves_setting_without_starting_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp)
            with mock.patch.object(boot,'configure',return_value=data), \
                 mock.patch.object(boot.sys,'argv',['beta_boot.py','--background-on']), \
                 mock.patch.object(boot.launcher,'start') as start, \
                 mock.patch('builtins.print'):
                self.assertEqual(boot.main(),0)
                start.assert_not_called()
            self.assertTrue(boot.background_setting(data)['keep_running_after_window_close'])

    def test_login_window_pins_exact_profile_and_quotes_special_characters(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp)/"profile ' ; $(never-run)";data.mkdir()
            scripts=Path(temp)/'scripts';scripts.mkdir()
            with mock.patch.object(boot.sys,'platform','darwin'), \
                 mock.patch.object(boot.tempfile,'mkdtemp',return_value=str(scripts)), \
                 mock.patch.object(boot.subprocess,'run') as run:
                self.assertEqual(boot.login_window(data),0)
            command=scripts/'登录当前研序测试空间.command'
            args=shlex.split(command.read_text().splitlines()[1])
            self.assertEqual(args[:3],['exec','env','RESEARCH_DESK_BETA_DATA_DIR='+str(data)])
            self.assertEqual(args[-1],'--login')
            self.assertEqual(args[-2],str(boot.ROOT/'beta_boot.py'))
            run.assert_called_once_with(['/usr/bin/open',str(command)],check=True)
            self.assertFalse((data/'auth.json').exists())
            if os.name!='nt':self.assertEqual(command.stat().st_mode & 0o777,0o700)

    def test_menu_data_folder_uses_configured_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp).resolve()/'isolated'
            with mock.patch.dict(os.environ,{'RESEARCH_DESK_BETA_DATA_DIR':str(data)}), \
                 mock.patch.object(boot.sys,'platform','darwin'), \
                 mock.patch.object(boot.sys,'argv',['beta_boot.py','--show-data']), \
                 mock.patch.object(boot.subprocess,'run') as run:
                self.assertEqual(boot.main(),0)
                self.assertEqual(os.environ['CODEX_HOME'],str(data/'codex'))
                run.assert_called_once_with(['/usr/bin/open',str(data)],check=True)

    def test_non_mac_rejects_native_entry_without_opening_terminal(self):
        with mock.patch.object(boot.sys,'platform','linux'),mock.patch.object(boot.subprocess,'run') as run:
            with self.assertRaises(RuntimeError):boot.login_window(Path('/synthetic'))
            run.assert_not_called()

    def test_host_routes_menu_through_its_environment_and_waits_for_startup_quit(self):
        host=(ROOT/'packaging/MacApp.swift').read_text()
        self.assertIn('boot(["--login-window"])',host)
        self.assertIn('boot(["--show-data"])',host)
        self.assertNotIn('NSWorkspace.shared.open(resources.appendingPathComponent("登录Codex.command"))',host)
        self.assertNotIn('if !ready { return .terminateNow }',host)
        self.assertIn('if self.terminating',host)
        self.assertIn('reply(toApplicationShouldTerminate: status == 0)',host)
        self.assertIn('return !keepRunningAfterClose',host)
        self.assertIn('guard alert.runModal() == .alertFirstButtonReturn else { return }',host)
        self.assertIn('boot(["--background-state"])',host)
        self.assertIn('window.isReleasedWhenClosed = false',host)
        self.assertIn('sender.orderOut(nil)',host)
        self.assertIn('@objc func showWindow()',host)
        self.assertIn('if !startingServer',host)
        self.assertIn('process.terminate()',host)
        self.assertIn('启动准备已取消；未启动服务',host)
        self.assertIn('if self.terminating {\n                NSApplication.shared.reply(toApplicationShouldTerminate: true)',host)


if __name__=='__main__':unittest.main()
