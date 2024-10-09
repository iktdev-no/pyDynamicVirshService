import os

from setuptools import setup
from DynamicVirshService import version

def readme():
    with open('README.md', encoding='utf-8') as f:
        return f.read()

setup(
    name="pyDynamicVirshService",
    long_description_content_type='text/markdown',
    long_description=readme(),
    packages=["DynamicVirshService"],
    install_requires=[
        "libvirt-python>=10.0.0",
        "paho-mqtt>=2.1.0"
    ],
    version=version.__version__,
    description="""
    A Python library to expose virtual machines to homeassistant over MQTT.
    """,
    python_requires=">=3.10.0",
    author="Brage Skjønborg",
    author_email="bskjon@outlook.com",
    url="https://github.com/iktdev-no/DynamicVirshService",
    classifiers=[
        "Intended Audience :: Developers",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Topic :: System :: Networking",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
