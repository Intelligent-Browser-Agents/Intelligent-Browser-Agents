"""
Setup configuration for ig_action_exec package
"""

from setuptools import setup, find_packages

setup(
    name="ig_action_exec",
    version="1.0.0",
    description="Browser action execution module for Information Gathering",
    author="IG Team",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "playwright>=1.40.0",
        "pydantic>=2.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
        ]
    }
)