#!/usr/bin/env python
#
# travis_after_all.py
#
# Retrieved from https://github.com/dmakhno/travis_after_all
#
# The main goal of this script to have a single publish when a build has
# several jobs. Currently the first job is a leader, meaning a node that will
# do the publishing.
#
#    The MIT License (MIT)
#
#    Copyright (c) 2014 Dmytro Makhno
#
#    Permission is hereby granted, free of charge, to any person obtaining a copy of
#    this software and associated documentation files (the "Software"), to deal in
#    the Software without restriction, including without limitation the rights to
#    use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
#    the Software, and to permit persons to whom the Software is furnished to do so,
#    subject to the following conditions:
#
#    The above copyright notice and this permission notice shall be included in all
#    copies or substantial portions of the Software.
#
#    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
#    FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
#    COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
#    IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
#    CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import os
import json
import time
import logging
import argparse

try:
    import urllib.request as urllib2
except ImportError:
    import urllib2



class JobStatus(object):
    def __init__(self, number, is_finished, is_succeeded, is_leader):
        self.is_finished = is_finished
        self.is_succeeded = is_succeeded
        self.number = number
        self.is_leader = is_leader

    def __str__(self):
        return '%s(F=%s,S=%s,N=%s,L=%s)' % (self.__class__.__name__,
                                            self.is_finished,
                                            self.is_succeeded,
                                            self.number,
                                            self.is_leader)

    @classmethod
    def from_matrix(cls, json_elem, leader_job_number):
        number = json_elem['number']
        is_finished = json_elem['finished_at'] is not None
        is_succeeded = json_elem['result'] == 0
        is_leader = number == leader_job_number

        return cls(number, is_finished, is_succeeded, is_leader)



class MatrixList(list):
    @classmethod
    def from_json(cls, raw_json, leader_job_number):
        matrix_elems = raw_json["matrix"]

        list_instance = cls()
        for matrix_elem in matrix_elems:
            log.info('converting from: %s' % matrix_elem)

            job_status = JobStatus.from_matrix(matrix_elem, leader_job_number)
            log.info('status: %s' % job_status)

            list_instance.append(job_status)

        return list_instance

    def __str__(self):
        elem_str = ','.join('%s=%s' % (e.number, e.is_succeeded)
                            for e in self)
        return '%s(%s)' % (self.__class__.__name__,
                           elem_str)

    @classmethod
    def snapshot(cls, travis_entry, travis_token, leader_job_number):
        log.info('Taking snapshot')
        headers = {'content-type': 'application/json'}
        if travis_token is None:
            log.info('No travis token')
        else:
            headers['Authorization'] = 'token {}'.format(travis_token)

        suffix = 'builds/%s' % build_id
        data = None

        raw_json = travis_get_json(travis_entry, suffix, data, headers=headers)

        log.info('Snapshot raw json: %s' % raw_json)

        return cls.from_json(raw_json, leader_job_number)

    @property
    def is_finished(self):
        return all(e.is_finished for e in self)

    @property
    def is_succeeded(self):
        return all(e.is_succeeeded for e in self)

    def get_waiting_str(self):
        return [','.join('%s' % e.number for e in self
                         if not e.is_finished)]

    @property
    def status(self):
        if self.is_finished:
            if self.is_succeeded:
                s = "others_succeeded"
            else:
                s = "others_failed"
        else:
            s = "others_busy"

        return s



def wait_others_to_finish(travis_entry, travis_token, leader_job_number):
    while True:
        matrix_list = MatrixList.snapshot(travis_entry, travis_token,
                                          leader_job_number)
        if all(elem.is_finished or elem.is_leader
               for elem in matrix_list):
            break

        log.info("Leader waits for minions: %s..." %
                 matrix_list.get_waiting_str())
        time.sleep(polling_interval)



def travis_get_json(travis_entry, suffix, data, headers=None):
    if headers is None:
        headers = {'content-type': 'application/json'}

    req = urllib2.Request("%s/%s" % (travis_entry, suffix),
                          json.dumps(data).encode('utf-8'), headers)
    response = urllib2.urlopen(req).read()
    json_content = json.loads(response.decode('utf-8'))
    return json_content



def get_token(travis_entry, gh_token):
    if gh_token is None or gh_token == "":
        log.info('GITHUB_TOKEN is not set, not using travis token')
        return None

    data = {"github_token": gh_token}
    json_content = travis_get_json(travis_entry, '/auth/github', data)

    travis_token = json_content.get('access_token')

    return travis_token



def get_argument_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--travis_entry',
                        default='https://api.travis-ci.org')
    parser.add_argument('--is_master', action="store_true")
    return parser



def current_job_is_leader(master_index):
    job_number = os.getenv(TRAVIS_JOB_NUMBER)
    return is_leader(master_index, job_number)



def is_leader(master_index, job_number):
    result = job_number.endswith('.%s' % master_index)
    log.info('is_leader %s %s: %s' % (master_index, job_number, result))



def get_job_number():
    return os.getenv(TRAVIS_JOB_NUMBER)



def report(output_dict):
    r = 'Report: ' + (';\n'.join('%s=%s' for k, v in output_dict.iteritems()))
    return r



if __name__ == '__main__':
    log = logging.getLogger("travis.leader")
    log.addHandler(logging.StreamHandler())
    log.setLevel(logging.INFO)

    TRAVIS_JOB_NUMBER = 'TRAVIS_JOB_NUMBER'
    TRAVIS_BUILD_ID = 'TRAVIS_BUILD_ID'
    POLLING_INTERVAL = 'LEADER_POLLING_INTERVAL'
    GITHUB_TOKEN = 'GITHUB_TOKEN'
    BUILD_AGGREGATE_STATUS = 'BUILD_AGGREGATE_STATUS'

    build_id = os.getenv(TRAVIS_BUILD_ID)
    polling_interval = int(os.getenv(POLLING_INTERVAL, '5'))
    gh_token = os.getenv(GITHUB_TOKEN)
    job_number = os.getenv(TRAVIS_JOB_NUMBER)

    parser = get_argument_parser()
    args = parser.parse_args()
    is_master = args.is_master

    travis_entry = args.travis_entry

    if job_number is None:
        # seems even for builds with only one job, this won't get here
        log.fatal("Don't use defining leader for build without matrix")
        exit(1)
    elif not is_master:
        # since python is subprocess, env variables are exported back via file
        log.info("This is a minion")
        output_dict = dict(BUILD_MINION="YES")
        report(output_dict)
        exit(0)

    log.info("This is a leader")
    travis_token = get_token(travis_entry, gh_token)

    leader_job_number = get_job_number()
    wait_others_to_finish(travis_entry, travis_token, leader_job_number)

    final_snapshot = MatrixList.snapshot(travis_entry, travis_token,
                                         leader_job_number)
    log.info("Final Results: %s" % final_snapshot)

    output_dict = dict(BUILD_LEADER="YES",
                       BUILD_AGGREGATE_STATUS=final_snapshot.status)
    report(output_dict)
