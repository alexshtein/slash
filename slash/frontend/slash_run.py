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
from xmlrpc.server import SimpleXMLRPCRequestHandler
from ..conf import config
from uuid import uuid4
import time
import subprocess
import threading
from ..parallel.worker_manager import WorkerManager
from ..parallel.server import Server
from ..parallel.worker import Worker
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
                        if config.root.run.worker_id:
                            worker = Worker(config.root.run.worker_id, collected)
                            worker.start()
                        else:
                            server = Server(collected, config.root.run.stop_on_error)
                            tr = threading.Thread(target=server.serve, args=())
                            tr.start()
                            worker_manager = WorkerManager(config.root.run.parallel, args)
                            worker_manager.start()
                            tr.join()
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





def slave1(channel):
    import time
    import random
    channel.send("ready")
    for x in channel:
        if x is None:  # we can shutdown
            break
        # sleep random time, send result
        time.sleep(random.randrange(3))
        from slash.frontend.slash_run import slash_run, _logger
        _logger.debug('before slash run')
        _logger.debug('a'*100)
        ret = 1 + 1
        channel.send(ret)

def master1(collected, num_slaves):
    args = ["tests/test_example.py", "--worker_id", '1']
    import slash.frontend.main
    #   from slash.frontend.main import main
    gw = execnet.makegateway()
    #ch = gw.remote_exec('import subprocess; subprocess.check_call("slash run -S {}", shell=True)'.format(' '.join(args)))
    ch = gw.remote_exec(slash.frontend.main)
    ch.send(args)
    for i in range(10):
        print (ch.receive())

    # group = execnet.Group()
    # for i in range(num_slaves):  # 4 CPUs
    #     group.makegateway()
    #
    # mch = group.remote_exec(main)
    # q = mch.make_receive_queue(endmarker=-1)
    # terminated = 0
    # tasks = [(test.__slash__.file_path, test.__slash__.function_name, test.__slash__.variation.id) for test in collected]
    # while 1:
    #     channel, item = q.get()
    #     if item == -1:
    #         terminated += 1
    #         print("terminated %s" % channel.gateway.id)
    #         if terminated == len(mch):
    #             print("got all results, terminating")
    #             break
    #         continue
    #     if item != "ready":
    #         print("other side %s returned %r" % (channel.gateway.id, item))
    #     if not tasks:
    #         print("no tasks remain, sending termination request to all")
    #         mch.send_each(None)
    #         tasks = -1
    #     if tasks and tasks != -1:
    #         task = tasks.pop()
    #         _logger.debug('sending slave')
    #         _logger.debug('a'*100)
    #         channel.send(task)
    #         print("sent task %r to %s" % (task, channel.gateway.id))
    #
    # group.terminate()
