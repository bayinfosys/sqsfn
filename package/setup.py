import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="sqsfn",
    version="0.0.1",
    author="ed",
    author_email="ed@bayis.co.uk",
    description="SQS Item processing callback",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/bayinfosys/sqsfn",
    packages=["sqsfn"],
    # FIXME: set entry_points
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
    install_requires=[
      "boto3",
    ],
    extras_require={
      "tests": [
        "hypothesis",
        "mock",
        "moto",
        "pytest",
      ],
    },
    test_suite="tests",
)
