# Copyright (c) 2026 RokctAI
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import ast
from compliance.base import PlatformComplianceVisitor, FILE_CHECKERS, collect_suppressions, is_suppressed
from compliance import controls

# Import all modules to trigger decorator registrations
import compliance.layer_2
import compliance.layer_3
import compliance.layer_4_5
import compliance.layer_6
import compliance.layer_7
import compliance.layer_8
import compliance.layer_9
import compliance.layer_10
import compliance.layer_11
import compliance.layer_12
import compliance.layer_13
import compliance.layer_14
import compliance.layer_15
import compliance.layer_16
import compliance.layer_17
import compliance.layer_18
import compliance.layer_19

# Expose key functions
from compliance.layer_3 import check_database_migrations


def scan_file(filepath, severity_overrides=None):
    errors = []
    if filepath.endswith(".py"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filepath)
            visitor = PlatformComplianceVisitor(filepath)
            visitor.visit(tree)
            errors.extend(visitor.errors)
        except Exception as e:
            errors.append({"line": 1, "type": "Syntax Error", "message": str(e)})

    # Run all other registered file checkers
    for checker in FILE_CHECKERS:
        errs = checker(filepath)
        if errs:
            errors.extend(errs)

    # Annotate every finding with its check-id, severity, and control IDs
    for err in errors:
        controls.annotate(err, severity_overrides)

    # Apply the unified suppression syntax (# compliance-ignore[-file]: <check-id>)
    # and drop checks configured "off".
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            file_level, line_level = collect_suppressions(f.read())
    except Exception:
        file_level, line_level = set(), {}

    errors = [
        e for e in errors
        if e["severity"] != "off"
        and not is_suppressed(e["check"], e.get("line", 1), file_level, line_level)
    ]
    return errors
