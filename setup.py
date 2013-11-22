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

from setuptools import setup, find_packages

import versioneer
versioneer.versionfile_source = "gilliam_aws/_version.py"
versioneer.versionfile_build = "gilliam_aws/_version.py"
versioneer.tag_prefix = ""
versioneer.parentdir_prefix = ""
commands = versioneer.get_cmdclass().copy()

setup(
    name="gilliam-aws",
    version=versioneer.get_version(),
    cmdclass=commands,
    packages=find_packages(),
    author="Johan Rydberg",
    author_email="johan.rydberg@gmail.com",
    description="Command-line tool for running Gilliam on AWS",
    license="Apache 2.0",
    keywords="app platform",
    url="https://github.com/gilliam/",
    install_requires=['boto', 'fabric', 'requests', 'gilliam-py', 'gilliam-cli'],
    entry_points={
        'gilliam.commands': [
            'aws create = gilliam_aws.commands:Create',
            'aws status = gilliam_aws.commands:Status',
            'aws destroy = gilliam_aws.commands:Destroy',
            ]
        },
)
