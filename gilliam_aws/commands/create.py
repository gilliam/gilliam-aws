# Copyright 2013 Johan Rydberg.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os
import random
import sys

from gilliam_client.config import StageConfig

from ..configure import Configure
from ..ec2 import AmazonWebServicesStage, connect


log = logging.getLogger(__name__)

_SERVICE_REGISTRY_IMAGE = 'quay.io/gilliam/service-registry'
_EXECUTOR_IMAGE = 'quay.io/gilliam/executor'
_BOOTSTRAP_IMAGE = 'quay.io/gilliam/bootstrap'


class Command(object):
    """\
    Create a new Gilliam stage running on Amazon Web Services:

      gilliam-aws create [options] app-prod

    Credentials for AWS is passed through the `--access-key-id` and
    `--secret-key` options or via the standard environment variables
    (`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`).

    For configuration, provide EC2 key pair with `--key-pair` and path
    to the corresponding SSH key file with `--ssh-key-file`.

    The stage is created in the EU east region unless region is
    specified with `--region`.
    """

    synopsis = 'Create stage'

    def __init__(self, parser):
        parser.add_argument('name')
        parser.add_argument('--access-key-id', metavar="DATA")
        parser.add_argument('--secret-access-key', metavar="DATA")
        parser.add_argument('--region', default='us-east-1', metavar="REGION")
        parser.add_argument('-k', '--key-pair', metavar="NAME")
        parser.add_argument('-i', '--ssh-key-file', metavar="PATH")
        parser.add_argument('--instance-type', default='m1.small', metavar="TYPE")
        parser.add_argument('-u', '--ssh-username', default='root', metavar="NAME")
        parser.add_argument('--repository', metavar="NAME")

    def handle(self, config, options):
        self._check_existing(config, options)
        stage_config = StageConfig.create(options.name)
        self._check_credentials(stage_config, options)
        self._build_config(stage_config, options)

        # step 1. create resources
        conn = connect(
            stage_config.get('aws_region'),
            aws_access_key_id=stage_config.get('aws_access_key_id'),
            aws_secret_access_key=stage_config.get('aws_secret_access_key'))
        stage = AmazonWebServicesStage.create(conn, stage_config,
                                              options.name)

        # step 2. configure resources
        configure = Configure(
            stage_config.get('aws_ssh_username'),
            stage_config.get('aws_ssh_key_file'))
        self._configure(stage, configure)
        self._bootstrap(stage, configure)

        # step 3. update stage config
        stage_config.set('service_registry', [
                'http://{0}:3222'.format(hostname)
                for (hostname, roles) in stage.iter_roles()
                if 'service-registry' in roles])
        if options.repository:
            stage_config.set('repository', options.repository)

        # stage 4. profit.
        stage_config.write()

    def _check_existing(self, config, options):
        """Make sure that there isn't a stage with this name already.
        If there is, panic.
        """
        try:
            log.debug("checking for existing stage ...")
            StageConfig.make(options.name)
        except EnvironmentError:
            pass
        else:
            sys.exit("there seem to be a stage with that name already")

    def _check_credentials(self, stage_config, options):
        """Make sure credentials are OK."""
        if not options.access_key_id:
            options.access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
        if not options.secret_access_key:
            options.secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
        if not options.key_pair:
            options.key_pair = os.getenv('AWS_KEYPAIR_NAME')
        if not options.ssh_key_file:
            options.ssh_key_file = os.getenv('AWS_SSH_PRIVKEY')

    def _build_config(self, stage_config, options):
        vars = [('aws_access_key_id', options.access_key_id, True),
                ('aws_secret_access_key', options.secret_access_key, True),
                ('aws_ec2_key_pair', options.key_pair, True),
                ('aws_ssh_key_file', options.ssh_key_file, True),
                ('aws_ssh_username', options.ssh_username, True),
                ('aws_region', options.region, True),
                ('aws_ec2_instance_type', options.instance_type, True)]
        for (var, value, required) in vars:
            if required and not value:
                sys.exit("config var %s is required" % (var,))
            stage_config.set(var, value)

    def _executor_name(self, node):
        return node.public_dns_name.split('.')[0]

    def _configure(self, stage, configure):
        """Set up basic configuration such as installing Docker (done
        by `configure`) and install components that lives outside of
        Gilliam such as the service-registry (executor depends on it)
        and the executor (the rest of the system depends on it).
        """
        for hostname, roles in stage.iter_roles():
            log.debug('configuring {0}'.format(hostname))
            with configure.configure(hostname):
                if 'service-registry' in roles:
                    self._start_service_registry(stage, hostname, configure)
                if 'executor' in roles:
                    self._start_executor(stage, hostname, configure)

    def _start_service_registry(self, stage, host, configure):
        service_registry_cluster = self._make_service_registry_option(stage)
        log.debug('launching service registry')
        options = '-n {0} -c {1}'.format(host, service_registry_cluster)
        configure.docker_run(_SERVICE_REGISTRY_IMAGE, options)

    def _start_executor(self, stage, host, configure):
        log.debug('launching executor')
        service_registry = self._make_service_registry_option(stage)
        options = '--host {0} --name {1}'.format(host, self._executor_name(host))
        env = {
            'GILLIAM_SERVICE_REGISTRY': service_registry,
            'DOCKER': 'http://{0}:3000'.format(host)
            }
        configure.docker_run(_EXECUTOR_IMAGE, options, env=env)

    def _bootstrap(self, stage, configure):
        """Run bootstrap script that will bring the system to life."""
        env = {
            # The bootstrap script need to know how to talk to the
            # service registry; fill in the service registry
            # environment variable so gilliam-cli knows where to pick
            # up the information.
            'GILLIAM_SERVICE_REGISTRY': self._make_service_registry_option(
                stage),

            # Routers need special attention since they are pinned to
            # specific executors.  The ROUTERS variable will hold a
            # space separated list of executor instance names that
            # should get a dedicated router.
            'ROUTERS': ' '.join(self._executor_name(host)
                                for (host, roles) in stage.iter_roles()
                                if 'router' in roles),
            }

        hostname = random.choice([h for (h, roles) in stage.iter_roles()])
        with configure.enter(hostname):
            log.debug("bootstrapping from {0}".format(hostname))
            configure.docker_run(_BOOTSTRAP_IMAGE, '', env, detach=False)

    def _make_service_registry_option(self, stage):
        return ','.join(
            '{0}:3222'.format(hostname)
            for (hostname, roles) in stage.iter_roles()
            if 'service-registry' in roles)
