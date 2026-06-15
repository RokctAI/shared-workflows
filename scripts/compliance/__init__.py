import ast
from compliance.base import PlatformComplianceVisitor, FILE_CHECKERS

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

def scan_file(filepath):
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
            
    return errors
