import itertools
import functools
import sys
import socket
import logbook
import execnet
from ..app import Application
from ..conf import config
from ..exception_handling import handling_exceptions
from ..exceptions import CannotLoadTests
from ..resuming import (get_last_resumeable_session_id, get_tests_to_resume, save_resume_state, clean_old_entries)
from ..runner import run_tests
from ..utils.interactive import generate_interactive_test
from ..utils.suite_files import iter_suite_file_paths
import xmlrpc.client
from xmlrpc.server import SimpleXMLRPCServer
from xmlrpc.server import SimpleXMLRPCRequestHandler
from ..conf import config
from uuid import uuid4
import queue
import time
_logger = logbook.Logger(__name__)

def slash_run(args, report_stream=None, resume=False, app_callback=None, working_directory=None):
    if report_stream is None:
        report_stream = sys.stderr
    app = Application()
    app.arg_parser.set_positional_metavar('TEST')
    if working_directory is not None:
        app.set_working_directory(working_directory)
    app.set_argv(args)
    app.set_report_stream(report_stream)
    app.enable_interactive()
    collected = []
    try:
        with app:
            if app_callback is not None:
                app_callback(app)
            try:
                with handling_exceptions():
                    if resume:
                        session_ids = app.positional_args
                        if not session_ids:
                            session_ids = [get_last_resumeable_session_id()]
                        to_resume = [x for session_id in session_ids for x in get_tests_to_resume(session_id)]
                        collected = app.test_loader.get_runnables(to_resume)
                    else:
                        collected = _collect_tests(app, args)
                    if app.parsed_args.interactive:
                        collected = itertools.chain([generate_interactive_test()], collected)
                with app.session.get_started_context():
                    if config.root.run.parallel:
                        server = Server(collected)
                        server.serve()
                        for i in range(config.root.run.parallel):
                            
                    elif config.root.run.is_slave:
                        client = Client(str(uuid4()), collected)
                        client.start()
                    else:
                        run_tests(collected)

            finally:
                save_resume_state(app.session.results, collected)
                clean_old_entries()
            if app.exit_code == 0 and not app.session.results.is_success(allow_skips=True):
                app.set_exit_code(-1)
    except Exception:         # pylint: disable=broad-except
        # Error reporting happens in app context
        assert app.exit_code != 0

    return app

slash_resume = functools.partial(slash_run, resume=True)


class Server(object):
    def __init__(self, tests):
        self.tests = tests
        self.not_started_tests = queue.Queue()
        self.finished_tests = []
        self.executing_tests = {}
        for i in range(len(tests)):
            self.not_started_tests.put(i)
        self.connected_clients = set()
        self.server = SimpleXMLRPCServer(("localhost", 8000), allow_none=True)
        self.server.register_instance(self)

    def has_unstarted_tests(self):
        return not self.not_started_tests.empty()

    def has_unfinished_tests(self):
        return len(self.finished_tests) < len(self.tests)

    def has_connected_clients(self):
        return len(self.connected_clients) != 0

    def connect(self, client_id):
        self.connected_clients.add(client_id)

    def get_test(self, client_id):
        if self.has_unstarted_tests():
            index = self.not_started_tests.get()
            test = self.tests[index]
            self.executing_tests[client_id] = index
            return (test.__slash__.file_path, test.__slash__.function_name, test.__slash__.variation.id)
        elif self.has_unfinished_tests():
            return "pending"
        else:
            self.connected_clients.remove(client_id)
            return "end"

    def finished_test(self, client_id):
        test_index = self.executing_tests.get(client_id, None)
        if test_index is not None:
            self.finished_tests.append(test_index)
            self.executing_tests[client_id] = None
        else:
            raise RuntimeError('bla')

    def serve(self):
        while self.has_unfinished_tests() or self.has_connected_clients():
            self.server.handle_request()


class Client(object):
    def __init__(self, client_id, collected_tests):
        self.client_id = client_id
        self.all_tests = collected_tests

    def find_test(self, func_data):
        for test in self.all_tests:
            if test.__slash__.file_path == func_data[0] and test.__slash__.function_name == func_data[1] and test.__slash__.variation.id == func_data[2]:
                return test

    def start(self):
        self.client = xmlrpc.client.ServerProxy('http://localhost:8000')
        self.client.connect(self.client_id)
        while True:
            import ipdb; ipdb.set_trace()
            func_data = self.client.get_test(self.client_id)
            if func_data == "end":
                break
            elif func_data == "pending":
                time.sleep(5)
                continue
            else:
                test = self.find_test(func_data)
                run_tests([test])
                self.client.finished_test(self.client_id)















def slave1(channel):
    import time
    import random
    channel.send("ready")
    for x in channel:
        if x is None:  # we can shutdown
            break
        # sleep random time, send result
        time.sleep(random.randrange(3))
        from slash.frontend.slash_run import slash_run, _logger, add
        from slash.frontend.main import main
        _logger.debug('before slash run')
        _logger.debug('a'*100)
        ret = add(1, 1)
        channel.send(ret)

def master1(collected, num_slaves):
    group = execnet.Group()
    for i in range(num_slaves):  # 4 CPUs
        group.makegateway()
    mch = group.remote_exec(slave)
    q = mch.make_receive_queue(endmarker=-1)
    terminated = 0
    tasks = [(test.__slash__.file_path, test.__slash__.function_name, test.__slash__.variation.id) for test in collected]
    while 1:
        channel, item = q.get()
        if item == -1:
            terminated += 1
            print("terminated %s" % channel.gateway.id)
            if terminated == len(mch):
                print("got all results, terminating")
                break
            continue
        if item != "ready":
            print("other side %s returned %r" % (channel.gateway.id, item))
        if not tasks:
            print("no tasks remain, sending termination request to all")
            mch.send_each(None)
            tasks = -1
        if tasks and tasks != -1:
            task = tasks.pop()
            _logger.debug('sending slave')
            _logger.debug('a'*100)
            channel.send(task)
            print("sent task %r to %s" % (task, channel.gateway.id))

    group.terminate()


def _collect_tests(app, args):  # pylint: disable=unused-argument
    paths = app.positional_args

    paths = _extend_paths_from_suite_files(paths)

    if not paths and not app.parsed_args.interactive:
        paths = config.root.run.default_sources


    if not paths and not app.parsed_args.interactive:
        raise CannotLoadTests("No tests specified")

    collected = app.test_loader.get_runnables(paths)
    if len(collected) == 0 and not app.parsed_args.interactive:
        raise CannotLoadTests("No tests could be collected")

    return collected

def _extend_paths_from_suite_files(paths):
    suite_files = config.root.run.suite_files
    if not suite_files:
        return paths
    paths = list(paths)
    paths.extend(iter_suite_file_paths(suite_files))
    return paths
