#!/usr/bin/env python
from __future__ import with_statement
from basetest import BaseTest
import sys, tempfile, os
from StringIO import StringIO
import unittest, signal
from logging import getLogger, WARN, ERROR
from contextlib import contextmanager

sys.path.insert(0, '..')

os.environ["http_proxy"] = "localhost:8000"

from zeroinstall.injector import model, gpg, download, trust, background, arch, selections, qdom, run
from zeroinstall.injector.policy import Policy
from zeroinstall.zerostore import Store, NotStored; Store._add_with_helper = lambda *unused: False
from zeroinstall.support import basedir, tasks
from zeroinstall.injector import fetch
import data
import my_dbus

import server

ran_gui = False
def raise_gui(*args):
	global ran_gui
	ran_gui = True
background._detach = lambda: False
background._exec_gui = raise_gui

@contextmanager
def output_suppressed():
	old_stdout = sys.stdout
	old_stderr = sys.stderr
	try:
		sys.stdout = StringIO()
		sys.stderr = StringIO()
		try:
			yield
		except Exception:
			raise
		except BaseException as ex:
			# Don't abort unit-tests if someone raises SystemExit
			raise Exception(str(type(ex)) + " " + str(ex))
	finally:
		sys.stdout = old_stdout
		sys.stderr = old_stderr

class Reply:
	def __init__(self, reply):
		self.reply = reply

	def readline(self):
		return self.reply

def download_and_execute(policy, prog_args, main = None):
	downloaded = policy.solve_and_download_impls()
	if downloaded:
		policy.config.handler.wait_for_blocker(downloaded)
	run.execute_selections(policy.solver.selections, prog_args, stores = policy.config.stores, main = main)

class NetworkManager:
	def state(self):
		return 3	# NM_STATUS_CONNECTED

class TestDownload(BaseTest):
	def setUp(self):
		BaseTest.setUp(self)

		self.config.handler.allow_downloads = True
		self.config.key_info_server = 'http://localhost:3333/key-info'

		self.config.fetcher = fetch.Fetcher(self.config)

		stream = tempfile.TemporaryFile()
		stream.write(data.thomas_key)
		stream.seek(0)
		gpg.import_key(stream)
		self.child = None

		trust.trust_db.watchers = []

	def tearDown(self):
		BaseTest.tearDown(self)
		if self.child is not None:
			os.kill(self.child, signal.SIGTERM)
			os.waitpid(self.child, 0)
			self.child = None

	def testRejectKey(self):
		with output_suppressed():
			self.child = server.handle_requests('Hello', '6FCF121BE2390E0B.gpg', '/key-info/key/DE937DD411906ACF7C263B396FCF121BE2390E0B')
			policy = Policy('http://localhost:8000/Hello', config = self.config)
			assert policy.need_download()
			sys.stdin = Reply("N\n")
			try:
				download_and_execute(policy, ['Hello'])
				assert 0
			except model.SafeException as ex:
				if "has no usable implementations" not in str(ex):
					raise ex
				if "Not signed with a trusted key" not in str(policy.handler.ex):
					raise ex
				self.config.handler.ex = None

	def testRejectKeyXML(self):
		with output_suppressed():
			self.child = server.handle_requests('Hello.xml', '6FCF121BE2390E0B.gpg', '/key-info/key/DE937DD411906ACF7C263B396FCF121BE2390E0B')
			policy = Policy('http://example.com:8000/Hello.xml', config = self.config)
			assert policy.need_download()
			sys.stdin = Reply("N\n")
			try:
				download_and_execute(policy, ['Hello'])
				assert 0
			except model.SafeException as ex:
				if "has no usable implementations" not in str(ex):
					raise ex
				if "Not signed with a trusted key" not in str(policy.handler.ex):
					raise
				self.config.handler.ex = None
	
	def testImport(self):
		from zeroinstall.injector import cli

		rootLogger = getLogger()
		rootLogger.disabled = True
		try:
			try:
				cli.main(['--import', '-v', 'NO-SUCH-FILE'], config = self.config)
				assert 0
			except model.SafeException as ex:
				assert 'NO-SUCH-FILE' in str(ex)
		finally:
			rootLogger.disabled = False
			rootLogger.setLevel(WARN)

		hello = self.config.iface_cache.get_feed('http://localhost:8000/Hello')
		self.assertEquals(None, hello)

		with output_suppressed():
			self.child = server.handle_requests('6FCF121BE2390E0B.gpg')
			sys.stdin = Reply("Y\n")

			assert not trust.trust_db.is_trusted('DE937DD411906ACF7C263B396FCF121BE2390E0B')
			cli.main(['--import', 'Hello'], config = self.config)
			assert trust.trust_db.is_trusted('DE937DD411906ACF7C263B396FCF121BE2390E0B')

			# Check we imported the interface after trusting the key
			hello = self.config.iface_cache.get_feed('http://localhost:8000/Hello', force = True)
			self.assertEquals(1, len(hello.implementations))

			# Shouldn't need to prompt the second time
			sys.stdin = None
			cli.main(['--import', 'Hello'], config = self.config)

	def testSelections(self):
		from zeroinstall.injector import cli
		root = qdom.parse(file("selections.xml"))
		sels = selections.Selections(root)
		class Options: dry_run = False

		with output_suppressed():
			self.child = server.handle_requests('Hello.xml', '6FCF121BE2390E0B.gpg', '/key-info/key/DE937DD411906ACF7C263B396FCF121BE2390E0B', 'HelloWorld.tgz')
			sys.stdin = Reply("Y\n")
			try:
				self.config.stores.lookup_any(sels.selections['http://example.com:8000/Hello.xml'].digests)
				assert False
			except NotStored:
				pass
			cli.main(['--download-only', 'selections.xml'], config = self.config)
			path = self.config.stores.lookup_any(sels.selections['http://example.com:8000/Hello.xml'].digests)
			assert os.path.exists(os.path.join(path, 'HelloWorld', 'main'))

			assert sels.download_missing(self.config) is None

	def testHelpers(self):
		from zeroinstall import helpers

		with output_suppressed():
			self.child = server.handle_requests('Hello.xml', '6FCF121BE2390E0B.gpg', '/key-info/key/DE937DD411906ACF7C263B396FCF121BE2390E0B', 'HelloWorld.tgz')
			sys.stdin = Reply("Y\n")
			sels = helpers.ensure_cached('http://example.com:8000/Hello.xml', config = self.config)
			path = self.config.stores.lookup_any(sels.selections['http://example.com:8000/Hello.xml'].digests)
			assert os.path.exists(os.path.join(path, 'HelloWorld', 'main'))
			assert sels.download_missing(self.config) is None

	def testSelectionsWithFeed(self):
		from zeroinstall.injector import cli
		root = qdom.parse(file("selections.xml"))
		sels = selections.Selections(root)

		with output_suppressed():
			self.child = server.handle_requests('Hello.xml', '6FCF121BE2390E0B.gpg', '/key-info/key/DE937DD411906ACF7C263B396FCF121BE2390E0B', 'HelloWorld.tgz')
			sys.stdin = Reply("Y\n")

			self.config.handler.wait_for_blocker(self.config.fetcher.download_and_import_feed('http://example.com:8000/Hello.xml', self.config.iface_cache))

			cli.main(['--download-only', 'selections.xml'], config = self.config)
			path = self.config.stores.lookup_any(sels.selections['http://example.com:8000/Hello.xml'].digests)
			assert os.path.exists(os.path.join(path, 'HelloWorld', 'main'))

			assert sels.download_missing(self.config) is None
	
	def testAcceptKey(self):
		with output_suppressed():
			self.child = server.handle_requests('Hello', '6FCF121BE2390E0B.gpg', '/key-info/key/DE937DD411906ACF7C263B396FCF121BE2390E0B', 'HelloWorld.tgz')
			policy = Policy('http://localhost:8000/Hello', config = self.config)
			assert policy.need_download()
			sys.stdin = Reply("Y\n")
			try:
				download_and_execute(policy, ['Hello'], main = 'Missing')
				assert 0
			except model.SafeException as ex:
				if "HelloWorld/Missing" not in str(ex):
					raise
	
	def testAutoAcceptKey(self):
		self.config.auto_approve_keys = True
		with output_suppressed():
			self.child = server.handle_requests('Hello', '6FCF121BE2390E0B.gpg', '/key-info/key/DE937DD411906ACF7C263B396FCF121BE2390E0B', 'HelloWorld.tgz')
			policy = Policy('http://localhost:8000/Hello', config = self.config)
			assert policy.need_download()
			sys.stdin = Reply("")
			try:
				download_and_execute(policy, ['Hello'], main = 'Missing')
				assert 0
			except model.SafeException as ex:
				if "HelloWorld/Missing" not in str(ex):
					raise

	def testDistro(self):
		with output_suppressed():
			native_url = 'http://example.com:8000/Native.xml'

			# Initially, we don't have the feed at all...
			master_feed = self.config.iface_cache.get_feed(native_url)
			assert master_feed is None, master_feed

			trust.trust_db.trust_key('DE937DD411906ACF7C263B396FCF121BE2390E0B', 'example.com:8000')
			self.child = server.handle_requests('Native.xml', '6FCF121BE2390E0B.gpg', '/key-info/key/DE937DD411906ACF7C263B396FCF121BE2390E0B')
			policy = Policy(native_url, config = self.config)
			assert policy.need_download()

			solve = policy.solve_with_downloads()
			self.config.handler.wait_for_blocker(solve)
			tasks.check(solve)

			master_feed = self.config.iface_cache.get_feed(native_url)
			assert master_feed is not None
			assert master_feed.implementations == {}

			distro_feed_url = master_feed.get_distro_feed()
			assert distro_feed_url is not None
			distro_feed = self.config.iface_cache.get_feed(distro_feed_url)
			assert distro_feed is not None
			assert len(distro_feed.implementations) == 2, distro_feed.implementations

	def testWrongSize(self):
		with output_suppressed():
			self.child = server.handle_requests('Hello-wrong-size', '6FCF121BE2390E0B.gpg',
							'/key-info/key/DE937DD411906ACF7C263B396FCF121BE2390E0B', 'HelloWorld.tgz')
			policy = Policy('http://localhost:8000/Hello-wrong-size', config = self.config)
			assert policy.need_download()
			sys.stdin = Reply("Y\n")
			try:
				download_and_execute(policy, ['Hello'], main = 'Missing')
				assert 0
			except model.SafeException as ex:
				if "Downloaded archive has incorrect size" not in str(ex):
					raise ex

	def testImplementationGenerateMissingId(self):
                old_out = sys.stdout
		try:
			sys.stdout = StringIO()
			self.child = server.handle_requests(('HelloWorld.tgz'))

                        from zeroinstall.zerostore import manifest
                        alg = manifest.get_algorithm('sha1')
                        assert alg

                        from zeroinstall.injector.reader import load_feed
			feed = load_feed(os.path.abspath('ImplementationNoId.xml'), True, False, False, alg, self.config)

                        expected_id = 'sha1=3ce644dc725f1d21cfcf02562c76f375944b266a'
                        assert feed.implementations[expected_id]
                        assert feed.implementations[expected_id].id == expected_id
		finally:
			sys.stdout = old_out

	def testArchiveGenerateMissingSize(self):
                old_out = sys.stdout
		try:
			sys.stdout = StringIO()
			self.child = server.handle_requests(('HelloWorld.tgz'))

                        from zeroinstall.injector.reader import load_feed
			feed = load_feed(os.path.abspath('MissingSize.xml'), True, False, True, None, self.config)

                        expected_id = 'sha1=3ce644dc725f1d21cfcf02562c76f375944b266a'
                        assert feed.implementations[expected_id].download_sources[0].size == 176
		finally:
			sys.stdout = old_out

	def testRecipe(self):
		old_out = sys.stdout
		try:
			sys.stdout = StringIO()
			self.child = server.handle_requests(('HelloWorld.tar.bz2', 'dummy_1-1_all.deb'))
			policy = Policy(os.path.abspath('Recipe.xml'), config = self.config)
			try:
				download_and_execute(policy, [])
				assert False
			except model.SafeException as ex:
				if "HelloWorld/Missing" not in str(ex):
					raise ex
		finally:
			sys.stdout = old_out

	def testRecipeUnpack(self):
		old_out = sys.stdout
		try:
			sys.stdout = StringIO()
			self.child = server.handle_requests(('doubly_packed.tar'))
			policy = Policy(os.path.abspath('Unpack.xml'), config = self.config)
			try:
				download_and_execute(policy, [])
				assert False
			except model.SafeException, ex:
				if "HelloWorld/Missing" not in str(ex):
					raise ex
		finally:
			sys.stdout = old_out

	def testSymlink(self):
		old_out = sys.stdout
		try:
			sys.stdout = StringIO()
			self.child = server.handle_requests(('HelloWorld.tar.bz2', 'HelloSym.tgz'))
			policy = Policy(os.path.abspath('RecipeSymlink.xml'), config = self.config)
			try:
				download_and_execute(policy, [])
				assert False
			except model.SafeException as ex:
				if 'Attempt to unpack dir over symlink "HelloWorld"' not in str(ex):
					raise
			self.assertEquals(None, basedir.load_first_cache('0install.net', 'implementations', 'main'))
		finally:
			sys.stdout = old_out

	def testAutopackage(self):
		old_out = sys.stdout
		try:
			sys.stdout = StringIO()
			self.child = server.handle_requests('HelloWorld.autopackage')
			policy = Policy(os.path.abspath('Autopackage.xml'), config = self.config)
			try:
				download_and_execute(policy, [])
				assert False
			except model.SafeException as ex:
				if "HelloWorld/Missing" not in str(ex):
					raise
		finally:
			sys.stdout = old_out

	def testRecipeFailure(self):
		old_out = sys.stdout
		try:
			sys.stdout = StringIO()
			self.child = server.handle_requests('*')
			policy = Policy(os.path.abspath('Recipe.xml'), config = self.config)
			try:
				download_and_execute(policy, [])
				assert False
			except download.DownloadError as ex:
				if "Connection" not in str(ex):
					raise
		finally:
			sys.stdout = old_out

	def testMirrors(self):
		old_out = sys.stdout
		try:
			sys.stdout = StringIO()
			getLogger().setLevel(ERROR)
			trust.trust_db.trust_key('DE937DD411906ACF7C263B396FCF121BE2390E0B', 'example.com:8000')
			self.child = server.handle_requests(server.Give404('/Hello.xml'), 'latest.xml', '/0mirror/keys/6FCF121BE2390E0B.gpg')
			policy = Policy('http://example.com:8000/Hello.xml', config = self.config)
			self.config.feed_mirror = 'http://example.com:8000/0mirror'

			refreshed = policy.solve_with_downloads()
			policy.handler.wait_for_blocker(refreshed)
			assert policy.ready
		finally:
			sys.stdout = old_out

	def testReplay(self):
		old_out = sys.stdout
		try:
			sys.stdout = StringIO()
			getLogger().setLevel(ERROR)
			iface = self.config.iface_cache.get_interface('http://example.com:8000/Hello.xml')
			mtime = int(os.stat('Hello-new.xml').st_mtime)
			self.config.iface_cache.update_feed_from_network(iface.uri, file('Hello-new.xml').read(), mtime + 10000)

			trust.trust_db.trust_key('DE937DD411906ACF7C263B396FCF121BE2390E0B', 'example.com:8000')
			self.child = server.handle_requests(server.Give404('/Hello.xml'), 'latest.xml', '/0mirror/keys/6FCF121BE2390E0B.gpg', 'Hello.xml')
			policy = Policy('http://example.com:8000/Hello.xml', config = self.config)
			self.config.feed_mirror = 'http://example.com:8000/0mirror'

			# Update from mirror (should ignore out-of-date timestamp)
			refreshed = policy.fetcher.download_and_import_feed(iface.uri, self.config.iface_cache)
			policy.handler.wait_for_blocker(refreshed)

			# Update from upstream (should report an error)
			refreshed = policy.fetcher.download_and_import_feed(iface.uri, self.config.iface_cache)
			try:
				policy.handler.wait_for_blocker(refreshed)
				raise Exception("Should have been rejected!")
			except model.SafeException as ex:
				assert "New feed's modification time is before old version" in str(ex)

			# Must finish with the newest version
			self.assertEquals(1235911552, self.config.iface_cache._get_signature_date(iface.uri))
		finally:
			sys.stdout = old_out

	def testBackground(self, verbose = False):
		p = Policy('http://example.com:8000/Hello.xml', config = self.config)
		self.import_feed(p.root, 'Hello.xml')
		p.freshness = 0
		p.network_use = model.network_minimal
		p.solver.solve(p.root, arch.get_host_architecture())
		assert p.ready, p.solver.get_failure_reason()

		@tasks.async
		def choose_download(registed_cb, nid, actions):
			try:
				assert actions == ['download', 'Download'], actions
				registed_cb(nid, 'download')
			except:
				import traceback
				traceback.print_exc()
			yield None

		global ran_gui
		ran_gui = False
		old_out = sys.stdout
		try:
			sys.stdout = StringIO()
			self.child = server.handle_requests('Hello.xml', '6FCF121BE2390E0B.gpg')
			my_dbus.system_services = {"org.freedesktop.NetworkManager": {"/org/freedesktop/NetworkManager": NetworkManager()}}
			my_dbus.user_callback = choose_download
			pid = os.getpid()
			old_exit = os._exit
			def my_exit(code):
				# The background handler runs in the same process
				# as the tests, so don't let it abort.
				if os.getpid() == pid:
					raise SystemExit(code)
				# But, child download processes are OK
				old_exit(code)
			from zeroinstall.injector import config
			key_info = config.DEFAULT_KEY_LOOKUP_SERVER
			config.DEFAULT_KEY_LOOKUP_SERVER = None
			try:
				try:
					os._exit = my_exit
					background.spawn_background_update(p, verbose)
					assert False
				except SystemExit as ex:
					self.assertEquals(1, ex.code)
			finally:
				os._exit = old_exit
				config.DEFAULT_KEY_LOOKUP_SERVER = key_info
		finally:
			sys.stdout = old_out
		assert ran_gui

	def testBackgroundVerbose(self):
		self.testBackground(verbose = True)

if __name__ == '__main__':
	unittest.main()
