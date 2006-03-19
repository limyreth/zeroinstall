import os
import gtk, gobject

import gui
import help_box
from dialog import Dialog
from zeroinstall.injector.iface_cache import iface_cache
from zeroinstall.injector import basedir, namespaces, model
from treetips import TreeTips

# Model columns
ITEM = 0
SELF_SIZE = 1
PRETTY_SIZE = 2
TOOLTIP = 3
DELETE_CB = 4

def pretty_size(size):
	if size == 0: return ''
	return gui.pretty_size(size)

def size_if_exists(path):
	"Get the size for a file, or 0 if it doesn't exist."
	if path and os.path.isfile(path):
		return os.path.getsize(path)
	return 0

def get_size(path):
	"Get the size for a directory tree. Get the size from the .manifest if possible."
	man = os.path.join(path, '.manifest')
	if os.path.exists(man):
		size = os.path.getsize(man)
		for line in file(man):
			if line[:1] in "XF":
				size += long(line.split(' ', 4)[3])
	else:
		size = 0
		for root, dirs, files in os.walk(path):
			for name in files:
				size += getsize(join(root, name))
	return size

def summary(iface):
	if iface.summary:
		return iface.get_name() + ' - ' + iface.summary
	return iface.get_name()

def delete_invalid_interface(uri):
	if not uri.startswith('/'):
		cached_iface = basedir.load_first_cache(namespaces.config_site,
				'interfaces', model.escape(uri))
		if cached_iface:
			#print "Delete", cached_iface
			os.unlink(cached_iface)
	user_overrides = basedir.load_first_config(namespaces.config_site,
				namespaces.config_prog,
				'user_overrides', model.escape(uri))
	if user_overrides:
		#print "Delete", user_overrides
		os.unlink(user_overrides)

def get_selected_paths(tree_view):
	"GTK 2.0 doesn't have this built-in"
	selection = tree_view.get_selection()
	paths = []
	def add(model, path, iter):
		paths.append(path)
	selection.selected_foreach(add)
	return paths

tips = TreeTips()

# Responses
DELETE = 0

class CacheExplorer(Dialog):
	def __init__(self):
		Dialog.__init__(self)
		self.set_title('Zero Install Cache')
		self.set_default_size(gtk.gdk.screen_width() / 2, gtk.gdk.screen_height() / 2)

		# Model
		self.model = gtk.TreeStore(str, int, str, str, object)
		self.tree_view = gtk.TreeView(self.model)

		# Tree view
		swin = gtk.ScrolledWindow()
		swin.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_ALWAYS)
		swin.set_shadow_type(gtk.SHADOW_IN)
		swin.add(self.tree_view)
		self.vbox.pack_start(swin, True, True, 0)
		self.tree_view.set_rules_hint(True)
		swin.show_all()

		column = gtk.TreeViewColumn('Item', gtk.CellRendererText(), text = ITEM)
		column.set_resizable(True)
		self.tree_view.append_column(column)

		cell = gtk.CellRendererText()
		cell.set_property('xalign', 1.0)
		column = gtk.TreeViewColumn('Size', cell, text = PRETTY_SIZE)
		self.tree_view.append_column(column)

		# Tree tooltips
		def motion(tree_view, ev):
			if ev.window is not tree_view.get_bin_window():
				return False
			pos = tree_view.get_path_at_pos(int(ev.x), int(ev.y))
			if pos:
				path = pos[0]
				row = self.model[path]
				tip = row[TOOLTIP]
				if tip:
					if tip != tips.item:
						tips.prime(tree_view, tip)
				else:
					tips.hide()
			else:
				tips.hide()

		self.tree_view.connect('motion-notify-event', motion)
		self.tree_view.connect('leave-notify-event', lambda tv, ev: tips.hide())

		# Responses

		self.add_button(gtk.STOCK_HELP, gtk.RESPONSE_HELP)
		self.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_OK)
		self.add_button(gtk.STOCK_DELETE, DELETE)
		self.set_default_response(gtk.RESPONSE_OK)

		selection = self.tree_view.get_selection()
		def selection_changed(selection):
			any_selected = False
			for x in get_selected_paths(self.tree_view):
				if not self.model[x][DELETE_CB]:
					self.set_response_sensitive(DELETE, False)
					return
				any_selected = True
			self.set_response_sensitive(DELETE, any_selected)
		selection.set_mode(gtk.SELECTION_MULTIPLE)
		selection.connect('changed', selection_changed)
		selection_changed(selection)

		def response(dialog, resp):
			if resp == gtk.RESPONSE_OK:
				self.destroy()
			elif resp == gtk.RESPONSE_HELP:
				cache_help.display()
			elif resp == DELETE:
				self.delete()
		self.connect('response', response)
	
	def delete(self):
		model = self.model
		paths = get_selected_paths(self.tree_view)
		paths.reverse()
		for path in paths:
			cb = model[path][DELETE_CB]
			assert cb
			cb(model[path][ITEM])
			model.remove(model.get_iter(path))
		self.update_sizes()

	def populate_model(self):
		# Find cached implementations

		unowned = {}	# Impl ID -> Store
		duplicates = []

		for s in iface_cache.stores.stores:
			for id in os.listdir(s.dir):
				if id in unowned:
					duplicates.append(id)
				unowned[id] = s

		ok_interfaces = []
		error_interfaces = []
		unused_interfaces = []

		# Look through cached interfaces for implementation owners
		all = iface_cache.list_all_interfaces()
		all.sort()
		for uri in all:
			iface_size = 0
			try:
				if uri.startswith('/'):
					cached_iface = uri
				else:
					cached_iface = basedir.load_first_cache(namespaces.config_site,
							'interfaces', model.escape(uri))
				user_overrides = basedir.load_first_config(namespaces.config_site,
							namespaces.config_prog,
							'user_overrides', model.escape(uri))

				iface_size = size_if_exists(cached_iface) + size_if_exists(user_overrides)
				iface = iface_cache.get_interface(uri)
			except Exception, ex:
				error_interfaces.append((uri, str(ex), iface_size))
			else:
				in_cache = []
				for impl in iface.implementations.values():
					if impl.id in unowned:
						impl_path = os.path.join(unowned[impl.id].dir, impl.id)
						impl_size = get_size(impl_path)
						in_cache.append((impl, impl_size))
						del unowned[impl.id]
						iface_size += impl_size
				if in_cache:
					in_cache.sort()
					ok_interfaces.append((iface, in_cache, iface_size))
				else:
					unused_interfaces.append((iface, iface_size))

		if error_interfaces:
			iter = self.model.append(None, [_("Invalid interfaces (unreadable)"),
						 0, None,
						 _("These interfaces exist in the cache but cannot be "
						   "read. You should probably delete them."),
						   None])
			for uri, ex, size in error_interfaces:
				self.model.append(iter, [uri, size, None, ex,
							 delete_invalid_interface])

		if unowned:
			unowned_sizes = []
			for id in unowned:
				impl_path = os.path.join(unowned[id].dir, id)
				unowned_sizes.append((get_size(impl_path), id, impl_path))
			iter = self.model.append(None, [_("Unowned implementations and temporary files"),
						0, None,
						_("These probably aren't needed any longer. You can "
						  "delete them."),
						  None])
			unowned_sizes.sort()
			for size, id, impl_path in unowned_sizes:
				self.model.append(iter, [id, size, None, impl_path,
				None])

		if unused_interfaces:
			iter = self.model.append(None, [_("Unused interfaces (no versions cached)"),
						0, None,
						_("These interfaces are cached, but no actual versions "
						  "are present. They might be useful, and they don't "
						  "take up much space."),
						  None])
			unused_interfaces.sort()
			for iface, size in unused_interfaces:
				self.model.append(iter, [iface.uri, size, None, summary(iface), None])

		if ok_interfaces:
			iter = self.model.append(None,
				[_("Used interfaces"),
				 0, None,
				 _("At least one implementation of each of "
				   "these interfaces is in the cache."),
				   None])
			for iface, in_cache, iface_size in ok_interfaces:
				iter2 = self.model.append(iter,
						  [iface.uri, iface_size, None, summary(iface), None])
				for impl, size in in_cache:
					self.model.append(iter2,
						['Version %s : %s' % (impl.get_version(), impl.id),
						 size, None,
						 None,
						 None])
		self.update_sizes()
	
	def update_sizes(self):
		"""Set PRETTY_SIZE to the total size, including all children."""
		m = self.model
		def update(itr):
			total = m[itr][SELF_SIZE]
			child = m.iter_children(itr)
			while child:
				total += update(child)
				child = m.iter_next(child)
			m[itr][PRETTY_SIZE] = pretty_size(total)
			return total
		itr = m.get_iter_root()
		while itr:
			update(itr)
			itr = m.iter_next(itr)

cache_help = help_box.HelpBox("Cache Explorer Help",
('Overview', """
When you run a program using Zero Install, it downloads the program's 'interface' file, \
which gives information about which versions of the program are available. This interface \
file is stored in the cache to save downloading it next time you run the program.

When you have chosen which version (implementation) of the program you want to \
run, Zero Install downloads that version and stores it in the cache too. Zero Install lets \
you have many different versions of each program on your computer at once. This is useful, \
since it lets you use an old version if needed, and different programs may need to use \
different versions of libraries in some cases.

The cache viewer shows you all the interfaces and implementations in your cache. \
This is useful to find versions you don't need anymore, so that you can delete them and \
free up some disk space.

Note: the cache viewer isn't finished; it doesn't currently let you delete things!"""),

('Invalid interfaces', """
The cache viewer gets a list of all interfaces in your cache. However, some may not \
be valid; they are shown in the 'Invalid interfaces' section. It should be fine to \
delete these. An invalid interface may be caused by a local interface that no longer \
exists, by a failed attempt to download an interface (the name ends in '.new'), or \
by the interface file format changing since the interface was downloaded."""),

('Unowned implementations and temporary files', """
The cache viewer searches through all the interfaces to find out which implementations \
they use. If no interface uses an implementation, it is shown in the 'Unowned implementations' \
section.

Unowned implementations can result from old versions of a program no longer being listed \
in the interface file. Temporary files are created when unpacking an implementation after \
downloading it. If the archive is corrupted, the unpacked files may be left there. Unless \
you are currently unpacking new programs, it should be fine to delete everything in this \
section."""),

('Unused interfaces', """
An unused interface is one which was downloaded, but you don't have any implementations in \
the cache. Since interface files are small, there is little point in deleting them. They may \
even be useful in some cases (for example, the injector sometimes checks multiple interfaces \
to find a usable version; if you delete one of them then it will have to fetch it again, because \
it will forget that it doesn't contain anything useful)."""),

('Used interfaces', """
All remaining interfaces are listed in this section. You may wish to delete old versions of \
certain programs. Deleting a program which you may later want to run will require it to be downloaded \
again. Deleting a version of a program which is currently running may cause it to crash, so be careful!
"""))