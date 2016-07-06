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
import sys
import json
import time
import logging
import argparse

try:
    from functools import reduce
except ImportError:
    pass

try:
    import urllib.request as urllib2
except ImportError:
    import urllib2



class MatrixElement(object):

    def __init__(self, json_raw):
        self.is_finished = json_raw['finished_at'] is not None
        self.is_succeeded = json_raw['result'] == 0
        self.number = json_raw['number']


def matrix_snapshot(travis_token, leader_job_number):
    """
    :return: Matrix List
    """
    headers = {'content-type': 'application/json', 'Authorization': 'token {}'.format(travis_token)}
    req = urllib2.Request("{0}/builds/{1}".format(travis_entry, build_id), headers=headers)
    response = urllib2.urlopen(req).read()
    raw_json = json.loads(response.decode('utf-8'))
    matrix_without_leader = [MatrixElement(job) for job in raw_json["matrix"]
                                    if not is_leader(leader_job_number, job['number'])]
    return matrix_without_leader


def wait_others_to_finish(travis_token):
    def others_finished():
        """
        Dumps others to finish
        Leader cannot finish, it is working now
        :return: tuple(True or False, List of not finished jobs)
        """
        snapshot = matrix_snapshot(travis_token)
        finished = [job.is_finished for job in snapshot]
        return all(finished), [job.number for job in snapshot
                                        if not job.is_finished]

    while True:
        finished, waiting_list = others_finished()
        if finished:
            break
        log.info("Leader waits for minions {0}...".format(waiting_list))  # just in case do not get "silence timeout"
        time.sleep(polling_interval)


def get_token(travis_entry, gh_token):
    assert gh_token, 'GITHUB_TOKEN is not set'
    data = {"github_token": gh_token}
    headers = {'content-type': 'application/json'}

    req = urllib2.Request("{0}/auth/github".format(travis_entry),
                            json.dumps(data).encode('utf-8'), headers)
    response = urllib2.urlopen(req).read()
    travis_token = json.loads(response.decode('utf-8')).get('access_token')

    return travis_token

def get_argument_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--travis_entry',
                        default='https://api.travis-ci.org')
    parser.add_argument('--is_master',action="store_true")


def current_job_is_leader(master_index):
    job_number=os.getenv(TRAVIS_JOB_NUMBER)
    return is_leader(master_index, job_number)


def is_leader(master_index, job_number):
     return job_number.endswith('.%s' % master_index)

def get_job_number():
    return os.getenv(TRAVIS_JOB_NUMBER)

if __name__=='__main__':
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


    parser=get_argument_parser()
    args=parser.parse_args()

    travis_entry = args.travis_entry

    if job_number is None:
        # seems even for builds with only one job, this won't get here
        log.fatal("Don't use defining leader for build without matrix")
        exit(1)
    elif not is_master:
        # since python is subprocess, env variables are exported back via file
        log.info("This is a minion")
        output_dict=dict(BUILD_MINION="YES")
        report(output_dict)
        exit(0)

    log.info("This is a leader")
    travis_token = get_token(travis_entry, gh_token)
    wait_others_to_finish(travis_token)

    leader_job_number=get_job_number()
    final_snapshot = matrix_snapshot(travis_token, leader_job_number)
    log.info("Final Results: {0}".format([(e.number, e.is_succeeded)
                                          for e in final_snapshot]))

    others_snapshot = [el for el in final_snapshot if not el.is_leader]
    if reduce(lambda a, b: a and b, [e.is_succeeded for e in others_snapshot]):
        os.environ[BUILD_AGGREGATE_STATUS] = "others_succeeded"
    elif reduce(lambda a, b: a and b, [not e.is_succeeded for e in others_snapshot]):
        log.error("Others Failed")
        os.environ[BUILD_AGGREGATE_STATUS] = "others_failed"
    else:
        log.warn("Others Unknown")
        os.environ[BUILD_AGGREGATE_STATUS] = "unknown"
    # since python is subprocess, env variables are exported back via file
    with open(".to_export_back", "w") as export_var:
        export_var.write("BUILD_LEADER=YES {0}={1}".format(BUILD_AGGREGATE_STATUS, os.environ[BUILD_AGGREGATE_STATUS]))

except Exception as e:
    log.fatal(e)
