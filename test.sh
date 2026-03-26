#!/bin/bash

# Create a temporary directory for the custom db
TEMP_DB=$(mktemp -d)
echo "Using temp db: $TEMP_DB"

# Run evid with --db option to create a dataset in the custom db
# Correct call: evid --db TEMP_DB set create -s test_ds
evid --db "$TEMP_DB" set create -s test_ds

# Check if the dataset was created in the custom db
if [ -d "$TEMP_DB/test_ds" ]; then
    echo "Test passed: dataset created in custom db"
else
    echo "Test failed: dataset not created"
    exit 1
fi

# Clean up the temporary directory
# rm -rf "$TEMP_DB"
