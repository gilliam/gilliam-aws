from setuptools import setup, find_packages

setup(
    name="gilliam-aws",
    version="0.1",
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
