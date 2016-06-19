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


import glob
import os

import jinja2
import markdown
import yaml

import obbenchlib


class HtmlGenerator(object):

    def __init__(self):
        self.statedir = None
        self.resultdir = None
        self.spec = None

    def generate_html(self):
        results = self.load_results()

        env = jinja2.Environment(
            loader=jinja2.PackageLoader('obbenchlib'),
            autoescape=lambda foo: True,
            extensions=['jinja2.ext.autoescape'])

        self.create_html_dir()
        page_classes = [
            FrontPage,
            BenchmarkPage,
            ProfileData,
            LogFile,
            CssFile,
        ]
        for page_class in page_classes:
            page = page_class()
            page.env = env
            page.results = results
            page.spec = self.spec

            for filename, data in page.generate():
                self.write_file(filename, data)

    @property
    def htmldir(self):
        return os.path.join(self.statedir, 'html')

    def create_html_dir(self):
        if not os.path.exists(self.htmldir):
            os.mkdir(self.htmldir)

    def load_results(self):
        results = []
        for filename in glob.glob(os.path.join(self.resultdir, '*.yaml')):
            with open(filename) as f:
                results.append(yaml.safe_load(f))
        return results

    def write_file(self, relative_path, text):
        filename = os.path.join(self.htmldir, relative_path)
        with open(filename, 'w') as f:
            f.write(text)


class HtmlPage(object):

    def __init__(self):
        self.env = None
        self.results = None
        self.spec = None

    def format_markdown(self, text):
        return markdown.markdown(text)

    def find_benchmark(self, benchmark_name):
        for benchmark in self.spec['benchmarks']:
            if benchmark['name'] == benchmark_name:
                return benchmark
        return {}

    @staticmethod
    def _get_step_name(step):
        for key in ['label', 'obnam']:
            if key in step:
                return step[key]
        raise RuntimeError("Don't know what to call step: %s" % (str(step), ))

    def get_step_names(self, benchmark):
        return map(self._get_step_name, benchmark['steps'])

    def generate(self):
        raise NotImplementedError()

    def render(self, template_name, variables):
        template = self.env.get_template(template_name)
        return template.render(**variables)


class FrontPage(HtmlPage):

    def generate(self):
        variables = {
            'description': self.format_markdown(self.spec['description']),
            'benchmark_names': [
                benchmark['name']
                for benchmark in sorted(self.spec['benchmarks'])
            ],
            'results_table': self.results_table(),
            'spec': yaml.safe_dump(
                self.spec, indent=4, default_flow_style=False)
        }
        yield 'index.html', self.render('index.j2', variables)

    def results_table(self):
        table = {}
        for result in self.results:
            key = '{commit_timestamp} {commit_id} {run_timestamp}'.format(
                **result)
            if key not in table:
                table[key] = {
                    'commit_id': result['commit_id'],
                    'commit_date': result['commit_date'],
                }
            table[key][result['benchmark_name']] = self.duration(result)

        return [table[key] for key in sorted(table.keys())]

    def duration(self, result):
        total = 0
        benchmark = self.find_benchmark(result['benchmark_name'])
        step_iter = zip(result['steps'], benchmark['steps'])
        for result_step, benchmark_step in step_iter:
            if benchmark_step.get('include_in_total', 'obnam' in benchmark_step):
              for key in result_step:
                  total += result_step[key].get('duration', 0)
        return total


class BenchmarkPage(HtmlPage):

    def generate(self):
        benchmark_names = [
            benchmark['name']
            for benchmark in self.spec['benchmarks']
        ]

        for benchmark_name in benchmark_names:
            yield self.generate_benchmark_page(benchmark_name)

    def generate_benchmark_page(self, benchmark_name):
        benchmark = self.find_benchmark(benchmark_name)
        table_rows = self.table_rows(benchmark)

        variables = {
            'benchmark_name': benchmark_name,
            'description': self.format_markdown(
                benchmark.get('description', '')),
            'table_rows': table_rows,
            'step_names': self.get_step_names(benchmark),
            'spec': yaml.safe_dump(
                benchmark, indent=4, default_flow_style=False)
        }

        return (
            '{}.html'.format(benchmark_name),
            self.render('benchmark.j2', variables)
        )

    def table_rows(self, benchmark):
        results = self.get_results_for_benchmark(benchmark)
        step_names = self.get_step_names(benchmark)
        rows = []
        for result in results:
            rows.append(self.table_row(result, step_names))
        return sorted(rows, key=lambda row: row['commit_timestamp'])

    def get_results_for_benchmark(self, benchmark):
        return [
            result
            for result in self.results
            if result['benchmark_name'] == benchmark['name']
        ]

    def table_row(self, result, step_names):
        row = {
            'result_id': result['result_id'],
            'commit_timestamp': result['commit_timestamp'],
            'commit_date': result['commit_date'],
            'commit_id': result['commit_id'],
            'total': 0,
            'vmrss_max': 0,
            'steps': [],
        }
        benchmark = self.find_benchmark(result['benchmark_name'])
        step_iter = zip(result['steps'], benchmark['steps'])
        for i, (result_step, benchmark_step) in enumerate(step_iter):
            for step_name in step_names:
                if step_name in result_step:
                    vmrss = result_step[step_name].get('vmrss', 0) / 1024 / 1024
                    row['steps'].append({
                        'filename_txt': '{}_{}.txt'.format(
                            result['result_id'], i),
                        'filename_prof': '{}_{}.prof'.format(
                            result['result_id'], i),
                        'filename_log': '{}_{}.log'.format(
                            result['result_id'], i),
                        'duration': result_step[step_name]['duration'],
                        'vmrss': vmrss,
                    })
                    if benchmark_step.get('include_in_total', 'obnam' in benchmark_step):
                        row['total'] += row['steps'][-1]['duration']
                    row['vmrss_max'] = max(row['vmrss_max'], vmrss)
                    break
        return row


class ProfileData(HtmlPage):

    def generate(self):
        for result in self.results:
            for i, step in enumerate(result['steps']):
                for operation in step:
                    if 'profile' in step[operation]:
                        yield self.generate_profile_data(
                            result, step, i, operation)
                        yield self.generate_profile_text(
                            result, step, i, operation)

    def generate_profile_data(self, result, step, i, operation):
        filename = '{}_{}.prof'.format(result['result_id'], i)
        return filename, step[operation]['profile']

    def generate_profile_text(self, result, step, i, operation):
        filename = '{}_{}.txt'.format(result['result_id'], i)
        return filename, step[operation]['profile-text']


class LogFile(HtmlPage):

    def generate(self):
        for result in self.results:
            for i, step in enumerate(result['steps']):
                for operation in step:
                    if 'log' in step[operation]:
                        yield self.generate_log_file(
                            result, step, i, operation)

    def generate_log_file(self, result, step, i, operation):
        filename = '{}_{}.log'.format(result['result_id'], i)
        return filename, step[operation]['log']


class CssFile(object):

    def generate(self):
        filename = os.path.join(
            os.path.dirname(obbenchlib.__file__), 'obbench.css')
        with open(filename) as f:
            data = f.read()
        yield 'obbench.css', data
