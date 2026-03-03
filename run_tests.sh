#!/bin/bash

# Get the absolute path of the project root directory
ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PYTHON_EXE=$( [ -d "$ROOT_DIR/venv" ] && echo "$ROOT_DIR/venv/bin/python3" || echo "python3" )

echo "Running Python Backend Tests..."
echo "------------------------------"

# Run unittest discovery
cd "$ROOT_DIR/backend" && "$PYTHON_EXE" -m unittest discover -p "test_*.py" -s "tests"

if [ $? -ne 0 ]; then
    echo "------------------------------"
    echo "SOME TESTS FAILED!"
    exit 1
fi

echo "------------------------------"
echo "All tests passed!"
