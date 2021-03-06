import itertools
import functools
import sys

import logbook

from ..app import Application
from ..conf import config
from ..exception_handling import handling_exceptions
from ..exceptions import CannotLoadTests
from ..resuming import (get_last_resumeable_session_id, get_tests_to_resume, save_resume_state, clean_old_entries)
from ..runner import run_tests
from ..utils.interactive import generate_interactive_test
from ..utils.suite_files import iter_suite_file_paths

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
