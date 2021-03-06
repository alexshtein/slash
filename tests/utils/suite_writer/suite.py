import itertools
import os
import sys
import tempfile
from contextlib import contextmanager

import gossip

from slash._compat import StringIO
from slash.conf import config
from slash.frontend.slash_run import slash_run

from ..code_formatter import CodeFormatter
from .file import File
from .slash_run_result import SlashRunResult
from .suite_strategy import BalancedStrategy
from .validation import validate_run, get_test_id_from_test_address


class Suite(object):

    def __init__(self, strategy=BalancedStrategy(), path=None, debug_info=True):
        super(Suite, self).__init__()
        self._path = path
        self._last_committed_path = None
        self.strategy = strategy
        self.debug_info = debug_info
        self.clear()

    def disable_debug_info(self):
        self.debug_info = False

    def deselect_all(self, exclude=()):
        for test in self:
            if test in exclude:
                continue
            test.expect_deselect()

    def populate(self, num_tests=10):
        for _ in range(num_tests):
            self.add_test()

    def clear(self):
        self._files = []
        self._notified = []
        self._num_method_tests = self._num_function_tests = 0
        self._slashconf = self._slashrc = None

    def iter_all_after(self, test, assert_has_more=False):
        found = had_more = False
        for t in self:
            if t == test:
                found = True
            elif found:
                had_more = True
                yield t
        if assert_has_more:
            assert had_more
        assert found

    @property
    def classes(self):
        return [cls for file in self._files for cls in file.classes]

    @property
    def files(self):
        return list(self._files)

    @property
    def slashconf(self):
        if self._slashconf is None:
            self._slashconf = File(self, relpath='slashconf.py')
        return self._slashconf

    @property
    def slashrc(self):
        if self._slashrc is None:
            self._slashrc = File(self, relpath='.slashrc')
        return self._slashrc

    def add_test(self, type=None, file=None):  # pylint: disable=unused-argument
        if type is None:
            type = self.strategy.get_test_type()
        if type == 'function':
            returned = self.add_function_test()
        elif type == 'method':
            returned = self.add_method_test()
        else:
            raise NotImplementedError('Unknown test type {0!r}'.format(type))  # pragma: no cover
        assert returned in self._notified
        return returned

    def add_method_test(self):
        cls = self.strategy.get_class_for_test(
            self.strategy.get_file_for_test(self))
        return cls.add_method_test()

    def add_function_test(self):
        return self.strategy.get_file_for_test(self).add_function_test()

    def notify_test_added(self, test):
        self._notified.append(test)
        if test.is_method_test():
            self._num_method_tests += 1
        else:
            self._num_function_tests += 1

    def add_file(self):
        returned = File(self)
        self._files.append(returned)
        return returned

    def get_last_file(self):
        if not self._files:
            return None
        return self._files[-1]

    def __len__(self):
        return len(self._notified)

    def __getitem__(self, idx):
        return self._notified[idx]

    def run(self, verify=True, expect_interruption=False, additional_args=(), args=None, commit=True, sort=True):
        if commit:
            self.commit()
        path = self._last_committed_path
        assert path is not None
        report_stream = StringIO()
        returned = SlashRunResult(report_stream=report_stream)
        captured = []
        with self._capture_events(returned), self._custom_sorting(sort):
            if args is None:
                args = [path]
            args.extend(additional_args)
            with self._custom_slashrc(path):
                app = slash_run(
                    args, report_stream=report_stream,
                    app_callback=captured.append,
                )
                returned.exit_code = app.exit_code
            if app.interrupted:
                assert expect_interruption, 'Unexpectedly interrupted'
            else:
                assert not expect_interruption, 'KeyboardInterrupt did not happen'

        if captured:
            assert len(captured) == 1
            returned.session = captured[0].session

        if verify:
            validate_run(self, returned, expect_interruption)
        return returned

    @contextmanager
    def _custom_sorting(self, do_sort):
        @gossip.register('slash.tests_loaded')
        def tests_loaded(tests):
            if do_sort:
                for test in tests:
                    test.__slash__.set_sort_key(self._get_test_id_from_runnable(test))
        try:
            yield
        finally:
            tests_loaded.gossip.unregister()


    def _get_test_id_from_runnable(self, test):
        return get_test_id_from_test_address(test.__slash__.address)

    @contextmanager
    def _custom_slashrc(self, path):
        if self._slashrc is None:
            yield
            return
        prev = config.root.run.user_customization_file_path
        config.root.run.user_customization_file_path = os.path.join(path, self._slashrc.get_relative_path())
        try:
            yield
        finally:
            config.root.run.user_customization_file_path = prev

    @contextmanager
    def _capture_events(self, summary):

        sys.modules['__ut__'] = summary.tracker
        try:
            yield
        finally:
            sys.modules.pop('__ut__')

    def commit(self):
        path = self._path
        if path is None:
            path = tempfile.mkdtemp()
        elif not os.path.isdir(path):
            os.makedirs(path)

        files = self._files
        if self._slashconf is not None:
            files = itertools.chain(files, [self._slashconf])
        if self._slashrc is not None:
            files = itertools.chain(files, [self._slashrc])


        # TODO: clean up paths  # pylint: disable=fixme
        for file in files:
            with open(os.path.join(path, file.get_relative_path()), 'w') as f:
                formatter = CodeFormatter(f)
                file.write(formatter)

        self._last_committed_path = path
        return path

    # Shortcuts

    @property
    def num_method_tests(self):
        return self._num_method_tests

    @property
    def num_function_tests(self):
        return self._num_function_tests

    @property
    def method_tests(self):
        return [test for test in self._notified if test.is_method_test()]

    @property
    def function_tests(self):
        return [test for test in self._notified if not test.is_method_test()]
