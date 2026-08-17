#!/usr/bin/env python3
"""
Replace MOCKED with DISABLED in comprehensive_suite.py
"""

import re

with open('institutional_integrations/comprehensive_suite.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace all MOCKED returns with DISABLED
content = re.sub(r'return \{"status": "MOCKED"', 'return {"status": "DISABLED"', content)

# Update error messages
content = re.sub(r'"status": "MOCKED"', '"status": "DISABLED"', content)

# Update MOCK references
content = re.sub(r'MOCK', 'DISABLED', content)

with open('institutional_integrations/comprehensive_suite.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Replaced MOCKED with DISABLED in comprehensive_suite.py')
