# pylint: disable=redefined-outer-name
import os
from tempfile import mkdtemp

import pytest
from slash import resuming
from slash.resuming import (CannotResume, get_last_resumeable_session_id, get_tests_to_resume, connecting_to_db)


@pytest.fixture
def patched_resume_dir(forge):
    path = mkdtemp()
    forge.replace_with(resuming, '_RESUME_DIR', path)
    return path

@pytest.fixture()
def set_resume_cwd(request):
    prev = os.getcwd()

    @request.addfinalizer
    def cleanup():
        os.chdir(prev)

def test_resume_no_session():
    with pytest.raises(CannotResume):
        with connecting_to_db() as conn:
            get_tests_to_resume("nonexisting_session", conn)


def test_get_last_resumeable_session(suite):
    suite[len(suite) // 2].when_run.fail()
    prev_id = None
    for i in range(5):  # pylint: disable=unused-variable
        results = suite.run()
        assert results.session.id != prev_id
        prev_id = results.session.id
        with connecting_to_db() as conn:
            assert get_last_resumeable_session_id(conn) == results.session.id


def test_resume(suite):
    fail_index = len(suite) // 2
    suite[fail_index].when_run.fail()
    for index, test in enumerate(suite):
        if index > fail_index:
            test.expect_not_run()
    result = suite.run(additional_args=['-x'])

    resumed = []
    with connecting_to_db() as conn:
        resumed = get_tests_to_resume(result.session.id, conn)

    assert len(resumed) + result.session.results.get_num_started() - 1 == len(suite)
    assert resumed[0].endswith(suite[fail_index].id)

def test_resume_with_parametrization(suite):
    num_values1 = 3
    num_values2 = 5
    test = suite.add_test(type='method')
    test.add_parameter(num_values=num_values1)
    test.add_parameter(num_values=num_values2)
    fail_index = len(suite) // 2
    suite[fail_index].when_run.fail()

    summary = suite.run()
    assert len(summary.get_all_results_for_test(test)) == num_values1 * num_values2
    with connecting_to_db() as conn:
        resumed = get_tests_to_resume(summary.session.id, conn)
        assert len(resumed) == 1

def test_different_folder_no_resume_session_id(suite, set_resume_cwd):
    fail_index = len(suite) // 2
    suite[fail_index].when_run.fail()
    suite.run()
    with connecting_to_db() as conn:
        sessoin_id = get_last_resumeable_session_id(conn)
        assert sessoin_id

    os.chdir(os.path.dirname(mkdtemp()))
    with pytest.raises(CannotResume):
        with connecting_to_db() as conn:
            sessoin_id = get_last_resumeable_session_id(conn)
