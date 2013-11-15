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

import contextlib
import logging
import os

from fabric.api import sudo, settings, hide
from fabric.network import disconnect_all


log = logging.getLogger(__name__)


class Configure(object):

    def __init__(self, username, ssh_key_file):
        self.username = username
        self.ssh_key_file = ssh_key_file

    def docker_run(self, image, command=None, ports=None, binds=None, env=None,
                   detach=True, open_stdin=False, tty=False):
        """Run a docker container."""
        options = []
        if detach:
            options.append('-d')
        if open_stdin:
            options.append('-i')
        if tty:
            options.append('-t')
        if ports:
            for port in ports:
                options.extend(['-p', port])
        if binds:
            for bind in binds:
                options.extend(['-v', bind])
        if env:
            for var, val in env.items():
                options.extend(['-e', '"{0}={1}"'.format(var, val)])
        sudo('docker -H 127.0.0.1:3000 run {options} {image} {command}'.format(
                options=' '.join(options), image=image,
                command=command or ''))
        
    @contextlib.contextmanager
    def configure(self, host):
        key_filename = os.path.expanduser(self.ssh_key_file)
        try:
            with settings(key_filename=key_filename,
                          user=self.username,
                          host_string=host):
                self._init()
                yield
        finally:
            with hide('status'):
                disconnect_all()

    @contextlib.contextmanager
    def enter(self, host):
        key_filename = os.path.expanduser(self.ssh_key_file)
        try:
            with settings(key_filename=key_filename,
                          user=self.username,
                          host_string=host):
                yield
        finally:
            with hide('status'):
                disconnect_all()

    def _init(self):
        """Perform basic initialization of the host; installs and
        starts docker.
        """
        sudo('curl https://get.docker.io/gpg | apt-key add -')
        sudo('echo "deb http://get.docker.io/ubuntu docker main" > /etc/apt/sources.list.d/docker.list')
        sudo('apt-get -qq update ')
        sudo('apt-get -qq install -y linux-image-extra-$(uname -r)')
        sudo('apt-get install -y lxc-docker')
        # XXX: right not we're running over HTTP to support WebSocket.
        sudo('sed -i "s#docker -d#docker -d -H 0.0.0.0:3000#g" /etc/init/docker.conf')
        sudo('service docker restart')
        sudo('modprobe aufs')
