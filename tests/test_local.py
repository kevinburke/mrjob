# Copyright 2009-2011 Yelp and Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for LocalMRJobRunner"""

from __future__ import with_statement

from StringIO import StringIO
import gzip
import mrjob
import os
import shutil
import signal
import stat
import sys
import tempfile

try:
    import unittest2 as unittest
except ImportError:
    import unittest

from mrjob.conf import dump_mrjob_conf
from mrjob.local import LocalMRJobRunner
from mrjob.util import cmd_line
from mrjob.util import read_file
from tests.mr_counting_job import MRCountingJob
from tests.mr_exit_42_job import MRExit42Job
from tests.mr_job_where_are_you import MRJobWhereAreYou
from tests.mr_test_jobconf import MRTestJobConf
from tests.mr_word_count import MRWordCount
from tests.mr_two_step_job import MRTwoStepJob
from tests.mr_verbose_job import MRVerboseJob
from tests.quiet import no_handlers_for_logger


class LocalMRJobRunnerEndToEndTestCase(unittest.TestCase):

    def setUp(self):
        self.make_tmp_dir_and_mrjob_conf()

    def tearDown(self):
        self.rm_tmp_dir()

    def make_tmp_dir_and_mrjob_conf(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.mrjob_conf_path = os.path.join(self.tmp_dir, 'mrjob.conf')
        dump_mrjob_conf({'runners': {'local': {}}},
                        open(self.mrjob_conf_path, 'w'))

    def rm_tmp_dir(self):
        shutil.rmtree(self.tmp_dir)

    def test_end_to_end(self):
        # read from STDIN, a regular file, and a .gz
        stdin = StringIO('foo\nbar\n')

        input_path = os.path.join(self.tmp_dir, 'input')
        with open(input_path, 'w') as input_file:
            input_file.write('bar\nqux\n')

        input_gz_path = os.path.join(self.tmp_dir, 'input.gz')
        input_gz_glob = os.path.join(self.tmp_dir, '*.gz')
        input_gz = gzip.GzipFile(input_gz_path, 'w')
        input_gz.write('foo\n')
        input_gz.close()

        mr_job = MRTwoStepJob(['-c', self.mrjob_conf_path,
                               '-', input_path, input_gz_glob])
        mr_job.sandbox(stdin=stdin)

        local_tmp_dir = None
        results = []

        with mr_job.make_runner() as runner:
            assert isinstance(runner, LocalMRJobRunner)
            runner.run()

            for line in runner.stream_output():
                key, value = mr_job.parse_output_line(line)
                results.append((key, value))

            local_tmp_dir = runner._get_local_tmp_dir()
            assert os.path.exists(local_tmp_dir)
            self.assertEqual(runner.counters()[0]['count']['combiners'], 8)

        # make sure cleanup happens
        assert not os.path.exists(local_tmp_dir)

        self.assertEqual(sorted(results),
                         [(1, 'qux'), (2, 'bar'), (2, 'foo'), (5, None)])

    def test_end_to_end_multiple_tasks(self):
        # read from STDIN, a regular file, and a .gz
        stdin = StringIO('foo\nbar\n')

        input_path = os.path.join(self.tmp_dir, 'input')
        with open(input_path, 'w') as input_file:
            input_file.write('bar\nqux\n')

        input_gz_path = os.path.join(self.tmp_dir, 'input.gz')
        input_gz = gzip.GzipFile(input_gz_path, 'w')
        input_gz.write('foo\n')
        input_gz.close()

        mr_job = MRTwoStepJob(['-c', self.mrjob_conf_path,
                               '--jobconf=mapred.map.tasks=2',
                                '--jobconf=mapred.reduce.tasks=2',
                               '-', input_path, input_gz_path])
        mr_job.sandbox(stdin=stdin)

        local_tmp_dir = None
        results = []

        with mr_job.make_runner() as runner:
            assert isinstance(runner, LocalMRJobRunner)
            runner.run()

            for line in runner.stream_output():
                key, value = mr_job.parse_output_line(line)
                results.append((key, value))

            local_tmp_dir = runner._get_local_tmp_dir()
            assert os.path.exists(local_tmp_dir)

        # make sure cleanup happens
        assert not os.path.exists(local_tmp_dir)

        self.assertEqual(sorted(results),
                         [(1, 'qux'), (2, 'bar'), (2, 'foo'), (5, None)])

    def test_get_file_splits_test(self):
        # set up input paths
        input_path = os.path.join(self.tmp_dir, 'input')
        with open(input_path, 'w') as input_file:
            input_file.write('bar\nqux\nfoo\nbar\nqux\nfoo\n')

        input_path2 = os.path.join(self.tmp_dir, 'input2')
        with open(input_path2, 'w') as input_file:
            input_file.write('foo\nbar\nbar\n')

        runner = LocalMRJobRunner(conf_path=False)

        # split into 3 files
        file_splits = runner._get_file_splits([input_path, input_path2], 3)

        # make sure we get 3 files
        self.assertEqual(len(file_splits), 3)

        # make sure all the data is preserved
        content = []
        for file_name in file_splits:
            f = open(file_name)
            content.extend(f.readlines())

        self.assertEqual(sorted(content),
                         ['bar\n', 'bar\n', 'bar\n', 'bar\n', 'foo\n',
                          'foo\n', 'foo\n', 'qux\n', 'qux\n'])

    def test_get_file_splits_sorted_test(self):
        # set up input paths
        input_path = os.path.join(self.tmp_dir, 'input')
        with open(input_path, 'w') as input_file:
            input_file.write(
                '1\tbar\n1\tbar\n1\tbar\n2\tfoo\n2\tfoo\n2\tfoo\n3\tqux\n'
                '3\tqux\n3\tqux\n')

        runner = LocalMRJobRunner(conf_path=False)

        file_splits = runner._get_file_splits([input_path], 3,
                                              keep_sorted=True)

        # make sure we get 3 files
        self.assertEqual(len(file_splits), 3)

        # make sure all the data is preserved in sorted order
        content = []
        for file_name in sorted(file_splits.keys()):
            f = open(file_name, 'r')
            content.extend(f.readlines())

        self.assertEqual(content,
                         ['1\tbar\n', '1\tbar\n', '1\tbar\n',
                          '2\tfoo\n', '2\tfoo\n', '2\tfoo\n',
                          '3\tqux\n', '3\tqux\n', '3\tqux\n'])

    def test_dont_split_gz(self):
        contents_gz = ['bar\n', 'qux\n', 'foo\n', 'bar\n', 'qux\n', 'foo\n']
        contents_normal = ['foo\n', 'bar\n', 'bar\n']
        all_contents_sorted = sorted(contents_gz + contents_normal)

        input_gz_path = os.path.join(self.tmp_dir, 'input.gz')
        input_gz = gzip.GzipFile(input_gz_path, 'w')
        input_gz.write(''.join(contents_gz))
        input_gz.close()

        input_path2 = os.path.join(self.tmp_dir, 'input2')
        with open(input_path2, 'w') as input_file:
            input_file.write(''.join(contents_normal))

        runner = LocalMRJobRunner(conf_path=False)

        # split into 3 files
        file_splits = runner._get_file_splits([input_gz_path, input_path2], 3)

        # Make sure that input.gz occurs in a single split that starts at
        # its beginning and ends at its end
        for split_info in file_splits.values():
            if split_info['orig_name'] == input_gz_path:
                self.assertEqual(split_info['start'], 0)
                self.assertEqual(split_info['length'],
                                 os.stat(input_gz_path)[stat.ST_SIZE])

        # make sure we get 3 files
        self.assertEqual(len(file_splits), 3)

        # make sure all the data is preserved
        content = []
        for file_name in file_splits:
            lines = list(read_file(file_name))

            # make sure the input_gz split got its entire contents
            if file_name == input_gz_path:
                self.assertEqual(lines, contents_gz)

            content.extend(lines)

        self.assertEqual(sorted(content),
                         all_contents_sorted)

    def test_multi_step_counters(self):
        stdin = StringIO('foo\nbar\n')

        mr_job = MRCountingJob(['-c', self.mrjob_conf_path, '-'])
        mr_job.sandbox(stdin=stdin)

        with mr_job.make_runner() as runner:
            runner.run()

            self.assertEqual(runner.counters(),
                             [{'group': {'counter_name': 2}},
                              {'group': {'counter_name': 2}},
                              {'group': {'counter_name': 2}}])


class LocalMRJobRunnerNoSymlinksTestCase(LocalMRJobRunnerEndToEndTestCase):
    """Test systems without os.symlink (e.g. Windows). See Issue #46"""

    def setUp(self):
        super(LocalMRJobRunnerNoSymlinksTestCase, self).setUp()
        self.remove_os_symlink()

    def tearDown(self):
        self.restore_os_symlink()
        super(LocalMRJobRunnerNoSymlinksTestCase, self).tearDown()

    def remove_os_symlink(self):
        if hasattr(os, 'symlink'):
            self._real_os_symlink = os.symlink
            del os.symlink  # sorry, were you using that? :)

    def restore_os_symlink(self):
        if hasattr(self, '_real_os_symlink'):
            os.symlink = self._real_os_symlink


class TimeoutException(Exception):
    pass


class LargeAmountsOfStderrTestCase(unittest.TestCase):

    def setUp(self):
        self.set_alarm()

    def tearDown(self):
        self.restore_old_alarm_handler()

    def set_alarm(self):
        # if the test fails, it'll stall forever, so set an alarm
        def alarm_handler(*args, **kwargs):
            raise TimeoutException('Stalled on large amounts of stderr;'
                                   ' probably pipe buffer is full.')
        self._old_alarm_handler = signal.signal(signal.SIGALRM, alarm_handler)
        signal.alarm(10)

    def restore_old_alarm_handler(self):
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self._old_alarm_handler)

    def test_large_amounts_of_stderr(self):
        mr_job = MRVerboseJob(['--no-conf'])
        mr_job.sandbox()

        try:
            with no_handlers_for_logger():
                mr_job.run_job()
        except TimeoutException:
            raise
        except Exception, e:
            # we expect the job to throw an exception

            # look for expected output from MRVerboseJob
            stderr = mr_job.stderr.getvalue()
            self.assertIn(
                "Counters from step 1:\n  Foo:\n    Bar: 10000", stderr)
            self.assertIn('status: 0\n', stderr)
            self.assertIn('status: 99\n', stderr)
            self.assertNotIn('status: 100\n', stderr)
            self.assertIn('STDERR: Qux\n', stderr)
            # exception should appear in exception message
            self.assertIn('BOOM', repr(e))
        else:
            raise AssertionError()


class ExitWithoutExceptionTestCase(unittest.TestCase):

    def test_exit_42_job(self):
        mr_job = MRExit42Job(['--no-conf'])
        mr_job.sandbox()

        try:
            mr_job.run_job()
        except Exception, e:
            self.assertIn('returned non-zero exit status 42', repr(e))
            return

        self.fail()


class PythonBinTestCase(unittest.TestCase):

    def test_echo_as_python_bin(self):
        # "echo" is a pretty poor substitute for Python, but it
        # should be available on most systems
        mr_job = MRTwoStepJob(['--python-bin', 'echo', '--no-conf'])
        mr_job.sandbox()

        with mr_job.make_runner() as runner:
            assert isinstance(runner, LocalMRJobRunner)
            runner.run()
            output = ''.join(runner.stream_output())

        # the output should basically be the command we used to
        # run the last step, which in this case is a mapper
        self.assertIn('mr_two_step_job.py', output)
        self.assertIn('--step-num=1', output)
        self.assertIn('--mapper', output)

    def test_python_dash_v_as_python_bin(self):
        python_cmd = cmd_line([sys.executable or 'python', '-v'])
        mr_job = MRTwoStepJob(['--python-bin', python_cmd, '--no-conf'])
        mr_job.sandbox(stdin=['bar\n'])

        with no_handlers_for_logger():
            mr_job.run_job()

        # expect debugging messages in stderr
        self.assertIn('import mrjob', mr_job.stderr.getvalue())
        self.assertIn('#', mr_job.stderr.getvalue())

        # should still get expected results
        self.assertEqual(sorted(mr_job.parse_output()),
                         [(1, None), (1, 'bar')])


class StepsPythonBinTestCase(unittest.TestCase):

    def test_echo_as_steps_python_bin(self):
        mr_job = MRTwoStepJob(
            ['--steps', '--steps-python-bin', 'echo', '--no-conf'])
        mr_job.sandbox()

        with mr_job.make_runner() as runner:
            assert isinstance(runner, LocalMRJobRunner)
            try:
                runner._get_steps()
                assert False, 'Should throw exception'
            except ValueError, ex:
                output = str(ex)
                # the output should basically be the command used to
                # run the steps command
                self.assertIn('mr_two_step_job.py', output)
                self.assertIn('--steps', output)


class LocalBootstrapMrjobTestCase(unittest.TestCase):

    def setUp(self):
        self.make_tmp_dir()

    def tearDown(self):
        self.rm_tmp_dir()

    def make_tmp_dir(self):
        self.tmp_dir = tempfile.mkdtemp()

    def rm_tmp_dir(self):
        shutil.rmtree(self.tmp_dir)

    def test_loading_boostrapped_mrjob_library(self):
        # track the dir we're loading mrjob from rather than the full path
        # to deal with edge cases where we load from the .py file,
        # and the script loads from the .pyc compiled from that .py file.
        our_mrjob_dir = os.path.dirname(os.path.realpath(mrjob.__file__))

        mr_job = MRJobWhereAreYou(['--no-conf'])
        mr_job.sandbox()

        with mr_job.make_runner() as runner:
            # sanity check
            self.assertEqual(runner.get_opts()['bootstrap_mrjob'], True)
            local_tmp_dir = os.path.realpath(runner._get_local_tmp_dir())

            runner.run()

            output = list(runner.stream_output())
            self.assertEqual(len(output), 1)

            # script should load mrjob from its working dir
            _, script_mrjob_dir = mr_job.parse_output_line(output[0])

            self.assertNotEqual(our_mrjob_dir, script_mrjob_dir)
            assert script_mrjob_dir.startswith(local_tmp_dir)

    def test_can_turn_off_bootstrap_mrjob(self):
        # track the dir we're loading mrjob from rather than the full path
        # to deal with edge cases where we load from the .py file,
        # and the script loads from the .pyc compiled from that .py file.
        our_mrjob_dir = os.path.dirname(os.path.realpath(mrjob.__file__))

        self.mrjob_conf_path = os.path.join(self.tmp_dir, 'mrjob.conf')
        dump_mrjob_conf({'runners': {'local': {'bootstrap_mrjob': False}}},
                        open(self.mrjob_conf_path, 'w'))

        mr_job = MRJobWhereAreYou(['-c', self.mrjob_conf_path])
        mr_job.sandbox()

        with mr_job.make_runner() as runner:
            # sanity check
            self.assertEqual(runner.get_opts()['bootstrap_mrjob'], False)
            runner.run()

            output = list(runner.stream_output())

            self.assertEqual(len(output), 1)

            # script should load mrjob from the same place our test does
            _, script_mrjob_dir = mr_job.parse_output_line(output[0])
            self.assertEqual(our_mrjob_dir, script_mrjob_dir)


class LocalMRJobRunnerTestJobConfCase(unittest.TestCase):

    def setUp(self):
        self.make_tmp_dir_and_mrjob_conf()

    def tearDown(self):
        self.rm_tmp_dir()

    def make_tmp_dir_and_mrjob_conf(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.mrjob_conf_path = os.path.join(self.tmp_dir, 'mrjob.conf')
        dump_mrjob_conf({'runners': {'local': {}}},
                        open(self.mrjob_conf_path, 'w'))

    def rm_tmp_dir(self):
        shutil.rmtree(self.tmp_dir)

    def test_input_file(self):
        input_path = os.path.join(self.tmp_dir, 'input')
        with open(input_path, 'w') as input_file:
            input_file.write('bar\nqux\nfoo\n')

        input_gz_path = os.path.join(self.tmp_dir, 'input.gz')
        input_gz = gzip.GzipFile(input_gz_path, 'w')
        input_gz.write('foo\n')
        input_gz.close()

        mr_job = MRWordCount(['-c', self.mrjob_conf_path,
                               '--jobconf=mapred.map.tasks=2',
                                '--jobconf=mapred.reduce.tasks=2',
                               input_path, input_gz_path])
        mr_job.sandbox()

        results = []

        with mr_job.make_runner() as runner:
            runner.run()

            for line in runner.stream_output():
                key, value = mr_job.parse_output_line(line)
                results.append((key, value))

            self.assertEqual(runner.counters()[0]['count']['combiners'], 2)

        self.assertEqual(sorted(results),
                         [(input_path, 3), (input_gz_path, 1)])

    def test_others(self):
        input_path = os.path.join(self.tmp_dir, 'input')
        with open(input_path, 'w') as input_file:
            input_file.write('foo\n')

        mr_job = MRTestJobConf(['-c', self.mrjob_conf_path,
                                '--jobconf=user.defined=something',
                               input_path])
        mr_job.sandbox()

        results = {}

        with mr_job.make_runner() as runner:
            runner.run()

            for line in runner.stream_output():
                key, value = mr_job.parse_output_line(line)
                results[key] = value

        self.assertEqual(results['mapreduce.job.cache.archives'],
                         runner._mrjob_tar_gz_path + '#mrjob.tar.gz')
        self.assertEqual(results['mapreduce.job.id'], runner._job_name)
        self.assertEqual(results['mapreduce.job.local.dir'],
                         runner._working_dir)
        self.assertEqual(results['mapreduce.map.input.file'], input_path)
        self.assertEqual(results['mapreduce.map.input.length'], '4')
        self.assertEqual(results['mapreduce.map.input.start'], '0')
        self.assertEqual(results['mapreduce.task.attempt.id'],
                       'attempt_%s_m_000000_0' % runner._job_name)
        self.assertEqual(results['mapreduce.task.id'],
                       'task_%s_m_000000' % runner._job_name)
        self.assertEqual(results['mapreduce.task.ismap'], 'true')
        self.assertEqual(results['mapreduce.task.output.dir'],
                         runner._output_dir)
        self.assertEqual(results['mapreduce.task.partition'], '0')
        self.assertEqual(results['user.defined'], 'something')


class CompatTestCase(unittest.TestCase):

    def test_environment_variables_018(self):
        runner = LocalMRJobRunner(hadoop_version='0.18', conf_path=False)
        # clean up after we're done. On windows, job names are only to
        # the millisecond, so these two tests end up trying to create
        # the same temp dir
        with runner as runner:
            runner._setup_working_dir()
            self.assertIn('mapred_cache_localArchives',
                          runner._subprocess_env('M', 0, 0).keys())

    def test_environment_variables_021(self):
        runner = LocalMRJobRunner(hadoop_version='0.21', conf_path=False)
        with runner as runner:
            runner._setup_working_dir()
            self.assertIn('mapreduce_job_cache_local_archives',
                          runner._subprocess_env('M', 0, 0).keys())
