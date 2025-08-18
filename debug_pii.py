#!/usr/bin/env python3

import logging
from src.common import PIIMaskingFormatter

# Test the PII masking formatter
formatter = PIIMaskingFormatter()

# Create a test record
record = logging.LogRecord('test', 10, 'test.py', 1, 'test', (), None)
record.msg = '{"email": "john@example.com", "phone": "+1234567890"}'
record.getMessage = lambda: record.msg

print('Original:', record.msg)
formatted = formatter.format(record)
print('Formatted:', formatted)
