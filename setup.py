#!/usr/bin/env python
# -*- coding: utf-8 -*-

try:
    import distribute_setup
    distribute_setup.use_setuptools()
except:
    pass

try:
    from setuptools import setup, find_packages
except ImportError:
    from distutils.core import setup

import os
import re


with open(os.path.join(os.path.dirname(__file__), 'influxtor', '__init__.py')) as f:
    version = re.search("__version__ = '([^']+)'", f.read()).group(1)

with open('requirements.txt', 'r') as f:
    requires = [x.strip() for x in f if x.strip()]

print requires

with open('README.rst', 'r') as f:
    readme = f.read()


setup(
    name='influxtor',
    version=version,
    description="Tornado Async InfluxDB client",
    long_description=readme,
    url='https://bitbucket.org/geehu/influxtor',
    license='MIT License',
    packages=find_packages(),
    install_requires=requires,
    author = "whb",
    author_email = "wanghongbin.whu@gmail.com"
)
