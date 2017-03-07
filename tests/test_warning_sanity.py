import pytest
from uuid import uuid4

import slash


def test_no_warnings_by_default(suite, suite_test, recwarn):  # pylint: disable=unused-argument
    suite.run()
    assert len(recwarn) == 0


@pytest.mark.parametrize('add_init_py', [True, False])
@pytest.mark.parametrize('utils_last', [True, False])
def test_relative_imports_no_warning(recwarn, tmpdir, add_init_py, utils_last):  # pylint: disable=unused-argument
    value = str(uuid4())

    tests = tmpdir.join('tests')
    utils_name = 'zzz' if utils_last else 'aaa'


    if add_init_py:
        with tests.join('__init__.py').open('w', ensure=True) as f:
            pass

    with tests.join('test_1.py').open('w', ensure=True) as f:
        print('from .{} import value'.format(utils_name), file=f)

        print('def test_something():', file=f)
        print('    pass', file=f)

    with tests.join('{}.py'.format(utils_name)).open('w') as f:
        f.write('value = {!r}'.format(value))

    with slash.Session() as session:
        tests = slash.loader.Loader().get_runnables([str(tests)])
    assert len(tests) == 1
    assert len(recwarn.list) == 0
    assert len(session.warnings) == 0
