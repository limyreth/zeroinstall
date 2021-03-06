"""
Executes a set of implementations as a program.
"""

# Copyright (C) 2009, Thomas Leonard
# See the README file for details, or visit http://0install.net.

from zeroinstall import _
import os, sys
from logging import info
from string import Template

from zeroinstall.injector.model import SafeException, EnvironmentBinding, Command, Dependency
from zeroinstall.injector import namespaces, qdom

def do_env_binding(binding, path):
	"""Update this process's environment by applying the binding.
	@param binding: the binding to apply
	@type binding: L{model.EnvironmentBinding}
	@param path: the selected implementation
	@type path: str"""
	os.environ[binding.name] = binding.get_value(path,
					os.environ.get(binding.name, None))
	info("%s=%s", binding.name, os.environ[binding.name])

def execute(policy, prog_args, dry_run = False, main = None, wrapper = None):
	"""Execute program. On success, doesn't return. On failure, raises an Exception.
	Returns normally only for a successful dry run.
	@param policy: a policy with the selected versions
	@type policy: L{policy.Policy}
	@param prog_args: arguments to pass to the program
	@type prog_args: [str]
	@param dry_run: if True, just print a message about what would have happened
	@type dry_run: bool
	@param main: the name of the binary to run, or None to use the default
	@type main: str
	@param wrapper: a command to use to actually run the binary, or None to run the binary directly
	@type wrapper: str
	@precondition: C{policy.ready and policy.get_uncached_implementations() == []}
	"""
	execute_selections(policy.solver.selections, prog_args, dry_run, main, wrapper)

def test_selections(selections, prog_args, dry_run, main, wrapper = None):
	"""Run the program in a child process, collecting stdout and stderr.
	@return: the output produced by the process
	@since: 0.27
	"""
	import tempfile
	output = tempfile.TemporaryFile(prefix = '0launch-test')
	try:
		child = os.fork()
		if child == 0:
			# We are the child
			try:
				try:
					os.dup2(output.fileno(), 1)
					os.dup2(output.fileno(), 2)
					execute_selections(selections, prog_args, dry_run, main)
				except:
					import traceback
					traceback.print_exc()
			finally:
				sys.stdout.flush()
				sys.stderr.flush()
				os._exit(1)

		info(_("Waiting for test process to finish..."))

		pid, status = os.waitpid(child, 0)
		assert pid == child

		output.seek(0)
		results = output.read()
		if status != 0:
			results += _("Error from child process: exit code = %d") % status
	finally:
		output.close()

	return results

def _process_args(args, element):
	"""Append each <arg> under <element> to args, performing $-expansion."""
	for child in element.childNodes:
		if child.uri == namespaces.XMLNS_IFACE and child.name == 'arg':
			args.append(Template(child.content).substitute(os.environ))

class Setup(object):
	"""@since: 1.1"""
	stores = None

	def __init__(self, stores):
		"""@param stores: where to find cached implementations
		@type stores: L{zerostore.Stores}"""
		self.stores = stores

	def build_command_args(self, selections, commands = None):
		"""Create a list of strings to be passed to exec to run the <command>s in the selections.
		@param selections: the selections containing the commands
		@type selections: L{selections.Selections}
		@param commands: the commands to be used (taken from selections is None)
		@type commands: [L{model.Command}]
		@return: the argument list
		@rtype: [str]"""

		prog_args = []
		commands = commands or selections.commands
		sels = selections.selections

		# Each command is run by the next, but the last one is run by exec, and we
		# need a path for that.
		if commands[-1].path is None:
			raise SafeException("Missing 'path' attribute on <command>")

		command_iface = selections.interface
		for command in commands:
			command_sel = sels[command_iface]

			command_args = []

			# Add extra arguments for runner
			runner = command.get_runner()
			if runner:
				command_iface = runner.interface
				_process_args(command_args, runner.qdom)

			# Add main program path
			command_path = command.path
			if command_path is not None:
				if command_sel.id.startswith('package:'):
					prog_path = command_path
				else:
					if command_path.startswith('/'):
						raise SafeException(_("Command path must be relative, but '%s' starts with '/'!") %
									command_path)
					prog_path = os.path.join(self._get_implementation_path(command_sel), command_path)

				assert prog_path is not None

				if not os.path.exists(prog_path):
					raise SafeException(_("File '%(program_path)s' does not exist.\n"
							"(implementation '%(implementation_id)s' + program '%(main)s')") %
							{'program_path': prog_path, 'implementation_id': command_sel.id,
							'main': command_path})

				command_args.append(prog_path)

			# Add extra arguments for program
			_process_args(command_args, command.qdom)

			prog_args = command_args + prog_args

		return prog_args

	def _get_implementation_path(self, impl):
		return impl.local_path or self.stores.lookup_any(impl.digests)

	def prepare_env(self, selections):
		"""Do all the environment bindings in selections (setting os.environ).
		@param selections: the selections to be used
		@type selections: L{selections.Selections}"""

		def _do_bindings(impl, bindings):
			for b in bindings:
				self.do_binding(impl, b)

		commands = selections.commands
		sels = selections.selections
		for selection in sels.values():
			_do_bindings(selection, selection.bindings)
			for dep in selection.dependencies:
				dep_impl = sels.get(dep.interface, None)
				if dep_impl is None:
					assert dep.importance != Dependency.Essential, dep
				elif not dep_impl.id.startswith('package:'):
					_do_bindings(dep_impl, dep.bindings)
		# Process commands' dependencies' bindings too
		# (do this here because we still want the bindings, even with --main)
		for command in commands:
			for dep in command.requires:
				dep_impl = sels.get(dep.interface, None)
				if dep_impl is None:
					assert dep.importance != Dependency.Essential, dep
				elif not dep_impl.id.startswith('package:'):
					_do_bindings(dep_impl, dep.bindings)
	
	def do_binding(self, impl, binding):
		"""Called by L{prepare_env} for each binding.
		Sub-classes may wish to override this."""
		if isinstance(binding, EnvironmentBinding):
			do_env_binding(binding, self._get_implementation_path(impl))

def execute_selections(selections, prog_args, dry_run = False, main = None, wrapper = None, stores = None):
	"""Execute program. On success, doesn't return. On failure, raises an Exception.
	Returns normally only for a successful dry run.
	@param selections: the selected versions
	@type selections: L{selections.Selections}
	@param prog_args: arguments to pass to the program
	@type prog_args: [str]
	@param dry_run: if True, just print a message about what would have happened
	@type dry_run: bool
	@param main: the name of the binary to run, or None to use the default
	@type main: str
	@param wrapper: a command to use to actually run the binary, or None to run the binary directly
	@type wrapper: str
	@since: 0.27
	@precondition: All implementations are in the cache.
	"""
	#assert stores is not None
	if stores is None:
		from zeroinstall import zerostore
		stores = zerostore.Stores()

	setup = Setup(stores)

	commands = selections.commands
	if main is not None:
		# Replace first command with user's input
		if main.startswith('/'):
			main = main[1:]			# User specified a path relative to the package root
		else:
			old_path = commands[0].path
			assert old_path, "Can't use a relative replacement main when there is no original one!"
			main = os.path.join(os.path.dirname(old_path), main)	# User main is relative to command's name
		# Copy all child nodes (e.g. <runner>) except for the arguments
		user_command_element = qdom.Element(namespaces.XMLNS_IFACE, 'command', {'path': main})
		if commands:
			for child in commands[0].qdom.childNodes:
				if child.uri == namespaces.XMLNS_IFACE and child.name == 'arg':
					continue
				user_command_element.childNodes.append(child)
		user_command = Command(user_command_element, None)
		commands = [user_command] + commands[1:]

	setup.prepare_env(selections)
	prog_args = setup.build_command_args(selections, commands) + prog_args

	if wrapper:
		prog_args = ['/bin/sh', '-c', wrapper + ' "$@"', '-'] + list(prog_args)

	if dry_run:
		print _("Would execute: %s") % ' '.join(prog_args)
	else:
		info(_("Executing: %s"), prog_args)
		sys.stdout.flush()
		sys.stderr.flush()
		try:
			os.execv(prog_args[0], prog_args)
		except OSError as ex:
			raise SafeException(_("Failed to run '%(program_path)s': %(exception)s") % {'program_path': prog_args[0], 'exception': str(ex)})
