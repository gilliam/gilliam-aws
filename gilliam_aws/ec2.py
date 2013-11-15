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
import time
import os

from boto.ec2 import connect_to_region


log = logging.getLogger(__name__)


AMI_MAPPING = {
    #'ap-northeast-1': 'ami-6b01666a',
    #'ap-southeast-1': 'ami-1cdf8a4e',
    'eu-west-1': 'ami-2adc3c5d',
    #'sa-east-1': 'ami-ab3791b6',
    #'us-east-1': 'ami-69d9fc00',
    ##'us-west-1': 'ami-40aa9c05',
    #'us-west-2': 'ami-b8b92288',
    }


def connect(region, **args):
    """Create a EC2 connection to a specific region.

    :returns: The EC2 connection object
    """
    return connect_to_region(region, **args)


def _get_or_make_group(conn, name):
    groups = conn.get_all_security_groups()
    group = [g for g in groups if g.name == name]
    if len(group) > 0:
        return group[0]
    else:
        log.info("creating security group %s" % (name,))
        return conn.create_security_group(name, "Gilliam EC2 group")


def _create_security_groups(conn, prefix, allowed, spec):
    groups = {name: _get_or_make_group(
                        conn, '{0}-{1}'.format(prefix, name))
              for name in spec.keys()}

    for name, rules in spec.items():
        group = groups.get(name)
        if group.rules:
            continue
        for rule in rules:
            if type(rule) in (tuple, list):
                for allow in allowed:
                    rule = list(rule) + [allow]
                    group.authorize(*rule)
            else:
                group.authorize(src_group=groups.get(rule))
    return groups


def _get_or_make_keypair(conn, key_dir, key_name):
    """Get or create a key pair with the given name."""
    try:
        key = conn.get_all_key_pairs(keynames=[key_name])[0]
    except conn.ResponseError, e:
        if e.code == 'InvalidKeyPair.NotFound':
            log.info("creating keypair {0}".format(key_name))
            # Create an SSH key to use when logging into instances.
            key = conn.create_key_pair(key_name)

            # Make sure the specified key_dir actually exists.
            # If not, create it.
            key_dir = os.path.expanduser(key_dir)
            key_dir = os.path.expandvars(key_dir)
            if not os.path.isdir(key_dir):
                os.makedirs(key_dir, 0700)

            # AWS will store the public key but the private key is
            # generated and returned and needs to be stored locally.
            # The save method will also chmod the file to protect
            # your private key.
            key.save(key_dir)
        else:
            raise
    return key


def _wait_for_system_and_instance_status_checks(conn, instances):
    """Wait for the given instances to pass system and instance status
    checks.
    """
    log.info("waiting for instances to pass system and status checks...")

    instance_ids = [i.id for i in instances]
    while True:
        statuses = conn.get_all_instance_status(instance_ids)
        pending = [status for status in statuses
                   if (status.system_status.status != 'ok'
                       or status.instance_status.status != 'ok')]
        if not pending:
            break
        time.sleep(5)


def _wait_for_instances_to_become_running(conn, instances):
    """Wait for given instances to become running."""
    while True:
        for i in instances:
            i.update()
        if len([i for i in instances if i.state == 'pending']) > 0:
            time.sleep(5)
        else:
            break

def _wait_for_instances(conn, instances):
    """Wait for instances to become fully ready."""
    _wait_for_instances_to_become_running(conn, instances)
    _wait_for_system_and_instance_status_checks(conn, instances)


def _reserve_instances(conn, config, security_groups, key_name):
    """Create instances based on the given configuration.  This
    implementation creates a single instance that has provides every
    role.

    :returns: The :class:`boto.ec2.instance.Reservation`.
    """
    ami = AMI_MAPPING[config.get('aws_region')]
    image = conn.get_all_images(image_ids=[ami])[0]
    return image.run(
        key_name=key_name,
        security_groups=security_groups.values(),
        instance_type=config.get('aws_ec2_instance_type'),
        min_count=1,
        max_count=1)


def _collect_instances(conn, name):
    """Givn a EC2 connection and a name, collect instances that
    belong to that stage.  Will only collect active instances.
    """
    instances = []
    for reservation in conn.get_all_instances():
        group_names = [g.name for g in reservation.groups]
        if any([group_name.startswith(name + '-') for group_name in group_names]):
            instances.extend(
                i for i in reservation.instances)
                #if is_active(i))
    return instances


# Check whether a given EC2 instance object is in a state we consider active,
# i.e. not terminating or terminated. We count both stopping and stopped as
# active since we can restart stopped clusters.
def is_active(instance):
    return (instance.state in ['pending', 'running', 'stopping', 'stopped'])


class AmazonWebServicesStage(object):

    SECURITY_GROUPS = {
        'router': [
            ('tcp', 22, 22),
            ('tcp', 8080, 8080),
            ],
        'exec': [
            'exec', 'router',
            ('tcp', 22, 22),
            ('tcp', 9000, 9000),
            ('tcp', 49153, 65535),    # the complete Docker port range
            ],
        'sr': [
            'exec', 'router',
            ('tcp', 3222, 3222)
            ],
        }


    def __init__(self, config, name, nodes, ssh_key_file=None):
        self.config = config
        self.name = name
        self.nodes = nodes
        self.username = 'ubuntu'
        self.ssh_key_file = ssh_key_file

    @classmethod
    def get(cls, conn, config, name):
        """Get an existing cluster if available."""
        nodes = _collect_instances(conn, name)
        if nodes:
            return cls(config, name, nodes)
        else:
            return None

    @classmethod
    def create(cls, conn, config, name, allowed=['0.0.0.0/0']):
        """
        Create a new stage running on Amazon Web Services. The stage
        config `config` provides data needed to bootstrap the stage.

        :param conn: AWS EC2 connection.
        :type conn: :class:`boto.ec2.connection.EC2Connection`.

        :param config: Stage configuration.
        :type config: :class:`gilliam_client.config.StageConfig`.

        :param name: The name of the stage.
        :type name: `str`.

        :returns: the created `AmazonWebServicesStage` object.
        """
        log.info("creating stage {0}".format(name))
        # FIXME: the path should not be specified here.
        key_name = name
        key_dir = os.path.expanduser("~/.gilliam/ec2-ssh-keys")
        key_pair = _get_or_make_keypair(conn, key_dir, key_name)
        security_groups = _create_security_groups(
            conn, name, allowed, AmazonWebServicesStage.SECURITY_GROUPS)
        res = _reserve_instances(conn, config, security_groups, key_name)
        _wait_for_instances(conn, res.instances)
        return cls(config, name, res.instances, ssh_key_file=os.path.join(
                key_dir, name + '.pem'))

    def destroy(self, conn):
        """Destroy the cluster by terminating all instances."""
        for inst in self.nodes:
            if inst.state not in ["shutting-down", "terminated"]:
                inst.terminate()

    def _roles(self, node):
        """From a EC2 instance try to decuce what roles it has.

        :type node: a :class:`boto.ec2.instance.Instance`
        """
        group_role_map = {
            'sr': 'service-registry',
            'exec': 'executor'
            }

        group_names = [g.name for g in node.groups]
        roles = []
        for group in group_names:
            if not group.startswith(self.name + '-'):
                continue
            role = group[len(self.name) + 1:]
            role = group_role_map.get(role, role)
            roles.append(role)
        return roles

    def iter_roles(self):
        """Return a sequence of `(hostname, roles)` tuples."""
        for node in self.nodes:
            yield node.public_dns_name, self._roles(node)
