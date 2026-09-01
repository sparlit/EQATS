# -*- coding: utf-8 -*-

import json
import os.path
import shutil
from datetime import date
from mail import notification

import pytest

today = str(date.today())
BASE_DIR = os.path.dirname(__file__)


def pytest_addoption(parser):
    group = parser.getgroup('count')
    group.addoption(
        '--count',
        action='store_true',
        dest='counter',
        default=False,
        help='Show number of erros '
    )


new_failures = {'erros': []}


filename = os.path.join(BASE_DIR, 'failures.json')
filename_old = os.path.join(BASE_DIR, 'old_failures.json')

@pytest.hookimpl
def pytest_sessionstart(session):
    global filename
    global filename_old

    if os.path.exists(filename):
        shutil.copy(filename, filename_old)
    else:
        filename_old = {'erros': []}


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    global new_failures
    global old_failures

    outcome = yield
    rep = outcome.get_result()
# ToDo: make it pretty
    if rep.when != 'call' or rep.fspath == 'tests/test_count.py':
        return

    if rep.failed:
        if 'tmpdir' in item.fixturenames:
            extra = ' (%s)' % item.funcargs['tmpdir']
        else:
            extra = ''

        new_failures['erros'].append({'id': rep.nodeid, 'extra': extra})

    with open(filename, 'w') as f:
        json.dump(new_failures, f)



@pytest.hookimpl
def pytest_sessionfinish(session):
    global filename
    global filename_old

    with open(filename, 'r') as f:
        new_count = f.readlines()
        new_data = json.loads(new_count[0])
    with open(filename_old, 'r') as f:
        old_count = f.readlines()
        old_data = json.loads(old_count[0])

    if len(new_data['erros']) > len(old_data['erros']):
        # send mail
        notification(len(new_data['erros']))
        print('send email')

