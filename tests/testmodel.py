#!/usr/bin/env python
# -*- coding: utf-8 -*-
import basetest
from basetest import BaseTest, empty_feed
import sys, os
from xml.dom import minidom
import unittest
from StringIO import StringIO

sys.path.insert(0, '..')
from zeroinstall.injector import model, qdom, namespaces

mydir = os.path.dirname(__file__)

class TestModel(BaseTest):
	def testLevels(self):
		assert model.network_offline in model.network_levels
		assert model.network_minimal in model.network_levels
		assert model.network_full in model.network_levels

	def testStabilities(self):
		assert 'insecure' in model.stability_levels
		assert 'buggy' in model.stability_levels
		assert 'developer' in model.stability_levels
		assert 'testing' in model.stability_levels
		assert 'stable' in model.stability_levels
		assert 'preferred' in model.stability_levels
		str(model.insecure)
	
	def testEscape(self):
		self.assertEquals("", model.escape(""))
		self.assertEquals("hello", model.escape("hello"))
		self.assertEquals("%20", model.escape(" "))

		self.assertEquals("file%3a%2f%2ffoo%7ebar",
				model.escape("file://foo~bar"))
		self.assertEquals("file%3a%2f%2ffoo%25bar",
				model.escape("file://foo%bar"))

		self.assertEquals("file:##foo%7ebar",
				model._pretty_escape("file://foo~bar"))
		self.assertEquals("file:##foo%25bar",
				model._pretty_escape("file://foo%bar"))

	def testUnescape(self):
		self.assertEquals("", model.unescape(""))
		self.assertEquals("hello", model.unescape("hello"))
		self.assertEquals(" ", model.unescape("%20"))

		self.assertEquals("file://foo~bar",
				model.unescape("file%3a%2f%2ffoo%7ebar"))
		self.assertEquals("file://foo%bar",
				model.unescape("file%3a%2f%2ffoo%25bar"))

		self.assertEquals("file://foo",
				model.unescape("file:##foo"))
		self.assertEquals("file://foo~bar",
				model.unescape("file:##foo%7ebar"))
		self.assertEquals("file://foo%bar",
				model.unescape("file:##foo%25bar"))
	
	def testEscaping(self):
		def check(str):
			self.assertEquals(str, model.unescape(model.escape(str)))
			self.assertEquals(str, model.unescape(model._pretty_escape(str)))

		check(u'http://example.com')
		check(u'http://example%46com')
		check(u'http:##example#com')
		check(u'http://example.com/foo/bar.xml')
		check(u'%20%21~&!"£ :@;,./{}$%^&()')

	def testBadInterface(self):
		try:
			model.Interface('foo')
			assert 0
		except model.SafeException:
			pass
	
	def testInterface(self):
		i = model.Interface('http://foo')
		self.assertEquals('(foo)', i.get_name())
		feed = model.ZeroInstallFeed(empty_feed, local_path = '/foo')
		self.assertEquals('Empty', feed.get_name())
		repr(i)

	def testMetadata(self):
		main_feed = model.ZeroInstallFeed(empty_feed, local_path = '/foo')
		e = qdom.parse(StringIO('<ns:b xmlns:ns="a" foo="bar"/>'))
		main_feed.metadata = [e]
		assert main_feed.get_metadata('a', 'b') == [e]
		assert main_feed.get_metadata('b', 'b') == []
		assert main_feed.get_metadata('a', 'a') == []
		assert e.getAttribute('foo') == 'bar'

	def testLocale(self):
		local_path = os.path.join(mydir, 'Local.xml')
		dom = qdom.parse(open(local_path))
		feed = model.ZeroInstallFeed(dom, local_path = local_path)
		# (defaults to en-US if no language is set in the locale)
		self.assertEquals("Local feed (English)", feed.summary)
		self.assertEquals("English", feed.description)

		self.assertEquals(4, len(feed.summaries))
		self.assertEquals(2, len(feed.descriptions))

		try:
			basetest.test_locale = ('es_ES', 'UTF8')

			self.assertEquals("Fuente local", feed.summary)
			self.assertEquals(u"Español", feed.description)

			basetest.test_locale = ('en_GB', 'UTF8')

			self.assertEquals("Local feed (English GB)", feed.summary)

			basetest.test_locale = ('fr_FR', 'UTF8')

			self.assertEquals("Local feed (English)", feed.summary)
			self.assertEquals("English", feed.description)
		finally:
			basetest.test_locale = (None, None)

	def testCommand(self):
		local_path = os.path.join(mydir, 'Command.xml')
		dom = qdom.parse(open(local_path))
		feed = model.ZeroInstallFeed(dom, local_path = local_path)

		assert feed.implementations['a'].main == 'foo'
		assert feed.implementations['a'].commands['run'].path == 'foo'
		assert feed.implementations['a'].commands['test'].path == 'test-foo'

		assert feed.implementations['b'].main == 'bar'
		assert feed.implementations['b'].commands['run'].path == 'bar'
		assert feed.implementations['b'].commands['test'].path == 'test-foo'

		assert feed.implementations['c'].main == 'runnable/missing'
		assert feed.implementations['c'].commands['run'].path == 'runnable/missing'
		assert feed.implementations['c'].commands['test'].path == 'test-baz'

	def testStabPolicy(self):
		i = model.Interface('http://foo')
		self.assertEquals(None, i.stability_policy)
		i.set_stability_policy(model.buggy)
		self.assertEquals(model.buggy, i.stability_policy)

	def testImpl(self):
		i = model.Interface('http://foo')
		a = model.ZeroInstallImplementation(i, 'foo', None)
		assert a.id == 'foo'
		assert a.size == a.version == a.user_stability == None
		assert a.arch == a.upstream_stability == None
		assert a.dependencies == {}
		assert a.download_sources == []
		assert a.get_stability() is model.testing
		a.upstream_stability = model.stable
		assert a.get_stability() is model.stable
		a.user_stability = model.buggy
		assert a.get_stability() is model.buggy
		a.version = model.parse_version('1.2.3')
		self.assertEquals('1.2.3', a.get_version())
		a.version = model.parse_version('1.2.3-rc2-post')
		self.assertEquals('1.2.3-rc2-post', a.get_version())
		assert str(a) == 'foo'

		b = model.ZeroInstallImplementation(i, 'foo', None)
		b.version = [1,2,1]
		assert b > a
	
	def testDownloadSource(self):
		f = model.ZeroInstallFeed(empty_feed, local_path = '/foo')
		a = model.ZeroInstallImplementation(f, 'foo', None)
		a.add_download_source('ftp://foo', 1024, None)
		a.add_download_source('ftp://foo.tgz', 1025, 'foo')
		assert a.download_sources[0].url == 'ftp://foo'
		assert a.download_sources[0].size == 1024
		assert a.download_sources[0].extract == None
		assert a.feed is f
		assert len(tuple(a.archives)) == 2
	
	def testEnvBind(self):
		a = model.EnvironmentBinding('PYTHONPATH', 'path')
		assert a.name == 'PYTHONPATH'
		assert a.insert == 'path'
		str(a)
	
	def testEnvModes(self):
		prepend = model.EnvironmentBinding('PYTHONPATH', 'lib', None, model.EnvironmentBinding.PREPEND)
		assert prepend.name == 'PYTHONPATH'
		assert prepend.insert == 'lib'
		assert prepend.mode is model.EnvironmentBinding.PREPEND

		self.assertEquals('/impl/lib:/usr/lib', prepend.get_value('/impl', '/usr/lib'))
		self.assertEquals('/impl/lib', prepend.get_value('/impl', None))

		append = model.EnvironmentBinding('PYTHONPATH', 'lib', '/opt/lib', model.EnvironmentBinding.APPEND)
		assert append.name == 'PYTHONPATH'
		assert append.insert == 'lib'
		assert append.mode is model.EnvironmentBinding.APPEND

		self.assertEquals('/usr/lib:/impl/lib', append.get_value('/impl', '/usr/lib'))
		self.assertEquals('/opt/lib:/impl/lib', append.get_value('/impl', None))
		
		append = model.EnvironmentBinding('PYTHONPATH', 'lib', None, model.EnvironmentBinding.REPLACE)
		assert append.name == 'PYTHONPATH'
		assert append.insert == 'lib'
		assert append.mode is model.EnvironmentBinding.REPLACE

		self.assertEquals('/impl/lib', append.get_value('/impl', '/usr/lib'))
		self.assertEquals('/impl/lib', append.get_value('/impl', None))

		assert model.EnvironmentBinding('PYTHONPATH', 'lib').mode == model.EnvironmentBinding.PREPEND

	def testOverlay(self):
		for xml, expected in [('<overlay/>', '<overlay . on />'),
				      ('<overlay src="usr"/>', '<overlay usr on />'),
				      ('<overlay src="package" mount-point="/usr/games"/>', '<overlay package on /usr/games>')]:
			e = qdom.parse(StringIO(xml))
			ol = model.process_binding(e)
			self.assertEquals(expected, str(ol))

			doc = minidom.parseString('<doc/>')
			new_xml = str(ol._toxml(doc).toxml())
			new_e = qdom.parse(StringIO(new_xml))
			new_ol = model.process_binding(new_e)
			self.assertEquals(expected, str(new_ol))
	
	def testDep(self):
		b = model.InterfaceDependency('http://foo', element = qdom.Element(namespaces.XMLNS_IFACE, 'requires', {}))
		assert not b.restrictions
		assert not b.bindings
		str(b)
	
	def testFeed(self):
		f = model.Feed('http://feed', arch = None, user_override = False)
		assert f.uri == 'http://feed'
		assert f.os == None
		assert f.machine == None
		assert f.arch == None
		assert f.user_override == False

		f = model.Feed('http://feed', arch = 'Linux-*', user_override = True)
		assert f.uri == 'http://feed'
		assert f.os == 'Linux'
		assert f.machine == None
		assert f.arch == 'Linux-*'
		assert f.user_override == True

		f = model.Feed('http://feed', arch = '*-i386', user_override = True)
		assert f.uri == 'http://feed'
		assert f.os == None
		assert f.machine == 'i386'
		assert f.arch == '*-i386'
		assert f.user_override == True
		assert str(f).startswith('<Feed from')

		try:
			f = model.Feed('http://feed', arch = 'i386', user_override = True)
			assert False
		except model.SafeException as ex:
			assert 'Malformed arch' in str(ex)
	
	def testCanonical(self):
		try:
			model.canonical_iface_uri('http://foo')
			assert False
		except model.SafeException as ex:
			assert 'Missing /' in str(ex)

		self.assertEquals('http://foo/',
				model.canonical_iface_uri('http://foo/'))
		try:
			model.canonical_iface_uri('bad-name')
			assert False
		except model.SafeException as ex:
			assert 'Bad interface name' in str(ex)
	
	def testVersions(self):
		def pv(v):
			parsed = model.parse_version(v)
			assert model.format_version(parsed) == v
			return parsed

		assert pv('1.0') > pv('0.9')
		assert pv('1.0') > pv('1')
		assert pv('1.0') == pv('1.0')
		assert pv('0.9.9') < pv('1.0')
		assert pv('10') > pv('2')

		def invalid(v):
			try:
				pv(v)
				assert False
			except model.SafeException:
				pass
		invalid('.')
		invalid('hello')
		invalid('2./1')
		invalid('.1')
		invalid('')

		# Check parsing
		assert pv('1') == [[1], 0]
		assert pv('1.0') == [[1,0], 0]
		assert pv('1.0-pre5') == [[1,0], -2, [5], 0]
		assert pv('1.0-rc5') == [[1,0], -1, [5], 0]
		assert pv('1.0-5') == [[1,0], 0, [5], 0]
		assert pv('1.0-post5') == [[1,0], 1, [5], 0]
		assert pv('1.0-post') == [[1,0], 1]
		assert pv('1-rc2.0-pre2-post') == [[1], -1, [2,0], -2, [2], 1]
		assert pv('1-rc2.0-pre-post') == [[1], -1, [2,0], -2, [], 1]

		assert pv('1.0-0') > pv('1.0')
		assert pv('1.0-1') > pv('1.0-0')
		assert pv('1.0-0') < pv('1.0-1')

		assert pv('1.0-pre99') > pv('1.0-pre1')
		assert pv('1.0-pre99') < pv('1.0-rc1')
		assert pv('1.0-rc1') < pv('1.0')
		assert pv('1.0') < pv('1.0-0')
		assert pv('1.0-0') < pv('1.0-post')
		assert pv('2.1.9-pre-1') > pv('2.1.9-pre')

		assert pv('2-post999') < pv('3-pre1')

if __name__ == '__main__':
	unittest.main()
