# Copyright 2015  Lars Wirzenius
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# =*= License: GPL-3+ =*=


import os
import random

import yaml


class Result(object):

    def __init__(self):
        self.benchmark_name = None
        self.run_timestamp = None
        self.commit_date = None
        self.commit_timestamp = None
        self.commit_id = None
        self._result_id = random.randint(0, 2**64-1)
        self._steps = []

    def start_step(self):
        self._steps.append({})

    def set_value(self, operation, kind, value):
        step = self._steps[-1]
        if operation not in step:
            step[operation] = {}
        step[operation][kind] = value

    def save_in_dir(self, dirname):
        o = {
            'result_id': self._result_id,
            'benchmark_name': self.benchmark_name,
            'run_timestamp': self.run_timestamp,
            'commit_date': self.commit_date,
            'commit_timestamp': self.commit_timestamp,
            'commit_id': self.commit_id,
            'steps': self._steps,
        }
        filename = os.path.join(dirname, '{}.yaml'.format(self._result_id))
        with open(filename, 'w') as f:
            yaml.safe_dump(o, stream=f)
