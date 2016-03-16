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
import pstats
import shutil
import StringIO
import tempfile
import time

import cliapp

import obbenchlib


class Benchmarker(object):

    profile_name = 'obnam.prof'

    def __init__(self):
        self.statedir = None
        self.gitdir = None
        self.resultdir = None
        self._livedir = None
        self._repodir = None
        self._srcdir = None
        self._config = None
        self._restored = None
        self._timestamp = None
        self.spec = None

    def run_benchmarks(self, ref):
        print
        print 'Running benchmarks for', ref
        print

        if not os.path.exists(self.resultdir):
            os.mkdir(self.resultdir)

        # We want to use the same timestamp for all benchmarks. This
        # is necessary so that all the benchmarks from one run for the
        # same commit are easy to align.
        self._timestamp = time.strftime('%Y-%m-%d %H:%M:%S')

        for benchmark in self.spec['benchmarks']:
            tempdir = self.create_temp_dir()
            self._livedir = self.create_subdir(tempdir, 'live')
            self._repodir = self.create_subdir(tempdir, 'repo')
            self._srcdir = self.create_subdir(tempdir, 'src')
            self._restored = self.create_subdir(tempdir, 'restored')
            self._logfile = os.path.join(tempdir, 'obnam.log')
            self._config = self.prepare_obnam_config(tempdir)

            self.prepare_obnam(ref)
            result = self.run_benchmark(benchmark)
            result.save_in_dir(self.resultdir)

            print 'Cleaning up'
            self.remove_temp_dir(tempdir)

    def create_temp_dir(self):
        return tempfile.mkdtemp()

    def create_subdir(self, parent, child):
        pathname = os.path.join(parent, child)
        os.mkdir(pathname)
        return pathname

    def remove_temp_dir(self, tempdir):
        shutil.rmtree(tempdir)

    def prepare_obnam_config(self, tempdir):
        config = os.path.join(tempdir, 'obnam.conf')
        with open(config, 'w') as f:
            f.write('[config]\n')
            f.write('quiet = no\n')
            f.write('repository = %s\n' % self._repodir)
            f.write('root = %s\n' % self._livedir)
            f.write('log-level = debug\n')
            f.write('log = %s\n' % self._logfile)
            for key, value in self.spec.get('obnam_config', {}).items():
                f.write('%s = %s\n' % (key, value))
        return config

    def prepare_obnam(self, ref):
        cliapp.runcmd(['git', 'clone', self.gitdir, self._srcdir])
        cliapp.runcmd(['git', 'checkout', ref], cwd=self._srcdir)
        cliapp.runcmd(
            ['python', 'setup.py', 'build_ext', '-i'],
            cwd=self._srcdir)

    def run_benchmark(self, benchmark):
        print 'Running benchmark {}'.format(benchmark['name'])
        result = obbenchlib.Result()
        result.benchmark_name = benchmark['name']
        result.run_timestamp = self._timestamp
        result.commit_date = self.get_commit_date()
        result.commit_timestamp = self.get_commit_timestamp()
        result.commit_id = self.get_commit_id()
        for step in benchmark['steps']:
            result.start_step()
            self.run_step(result, step)
        print
        return result

    def get_commit_date(self):
        timestamp = self.get_commit_timestamp()
        return timestamp.split()[0]

    def get_commit_timestamp(self):
        output = cliapp.runcmd(
            ['git', 'show', '--date=iso', 'HEAD'],
            cwd=self._srcdir)
        for line in output.splitlines():
            if line.startswith('Date:'):
                return line[len('Date:'):].strip()
        raise Exception('commit has no Date:')

    def get_commit_id(self):
        output = cliapp.runcmd(['git', 'rev-parse', 'HEAD'], cwd=self._srcdir)
        return output.strip()

    def run_step(self, result, step):
        if 'live' in step:
            self.run_step_live(result, step['live'])
        self.run_step_obnam(result, step['obnam'])

    def run_step_live(self, result, shell_command):
        print 'Running live:', shell_command
        started = time.time()
        cliapp.runcmd(['sh', '-euc', shell_command], cwd=self._livedir)
        duration = time.time() - started
        result.set_value('live', 'duration', duration)

    def run_step_obnam(self, result, obnam_subcommand):
        print 'Running obnam:', obnam_subcommand

        # Remove Obnam log file so it we later collect only the log
        # for one invocation.
        if os.path.exists(self._logfile):
            os.remove(self._logfile)

        funcs = {
            'backup': self.run_obnam_backup,
            'restore': self.run_obnam_restore,
            'forget': self.run_obnam_forget,
        }
        started = time.time()
        funcs[obnam_subcommand]()
        duration = time.time() - started

        result.set_value(obnam_subcommand, 'duration', duration)
        result.set_value(obnam_subcommand, 'profile', self.read_profile())
        result.set_value(
            obnam_subcommand, 'profile-text', self.read_profile_text())

        log = self.read_log_file()
        result.set_value(obnam_subcommand, 'log', log)
        result.set_value(obnam_subcommand, 'vmrss', self.find_max_vmrss(log))

    def run_obnam_backup(self):
        self.run_obnam(['backup'])

    def run_obnam_restore(self):
        cliapp.runcmd(['find', self._restored, '-delete'])
        self.run_obnam(['restore', '--to', self._restored])

    def run_obnam_forget(self):
        self.run_obnam(['forget'])

    def run_obnam(self, args):
        env = dict(os.environ)
        env['OBNAM_PROFILE'] = self.profile_name
        opts = ['--no-default-config', '--config', self._config]
        cliapp.runcmd(
            ['./obnam'] + opts + args,
            env=env,
            cwd=self._srcdir)

    def read_profile(self):
        filename = os.path.join(self._srcdir, self.profile_name)
        with open(filename) as f:
            return f.read()

    def read_log_file(self):
        with open(self._logfile) as f:
            return f.read()

    def find_max_vmrss(self, log_text):
        vmrss = 0
        for line in log_text.splitlines():
            words = line.split()
            if len(words) == 6 and words[2:4] == ['DEBUG', 'VmRSS:']:
                vmrss = max(vmrss, int(words[4]))
        return vmrss * 1024

    def read_profile_text(self):
        f = StringIO.StringIO()
        filename = os.path.join(self._srcdir, self.profile_name)
        p = pstats.Stats(filename, stream=f)
        p.strip_dirs()
        p.sort_stats('cumulative')
        p.print_stats()
        p.print_callees()
        return f.getvalue()
