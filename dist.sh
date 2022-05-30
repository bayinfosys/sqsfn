#!/bin/bash

pushd package

python3 -m build || exit 1
ls -la . dist
python3 -m twine upload dist/* --verbose || exit 1
rm -drf bayis_sqs_callback.egg-info/ dist/
