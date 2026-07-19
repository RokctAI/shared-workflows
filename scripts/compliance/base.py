import ast
import fnmatch
import re


# ── Shared helpers ───────────────────────────────────────────────────────────

# API paths where @frappe.whitelist functions are expected to live. Shared by
# layer_2 (type safety) and layer_12 (observability) — keep the single copy here.
KNOWN_API_PATHS = [
    "*/api/auth/*",
    "*/api/brain/*",
    "*/api/plan_builder/*",
    "*/api/setup/*",
    "*/betassist/api*",
]


def get_known_api_paths(filename):
    """Return the known API path globs, plus a dynamic glob for the file's
    top-level app directory (the scanner always runs from repo root, so the
    first non-'.' path segment IS the app/module name)."""
    paths = list(KNOWN_API_PATHS)
    normalized = filename.replace("\\", "/").lower()
    parts = [p for p in normalized.split("/") if p and p != "."]
    if parts:
        paths.append(f"*/{parts[0]}/*")
    return paths


def matches_known_api_path(filename):
    normalized = filename.replace("\\", "/").lower()
    return any(fnmatch.fnmatch(normalized, x) for x in get_known_api_paths(filename))


def is_frappe_whitelisted(node):
    """True if a FunctionDef carries a (frappe.)whitelist decorator."""
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name) and target.id == "whitelist":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "whitelist":
            return True
    return False


# ── Unified suppression syntax ───────────────────────────────────────────────
#
#   # compliance-ignore: <check-id>[, <check-id>...]      (same line or line above)
#   # compliance-ignore-file: <check-id>[, ...] | all     (anywhere in file)
#
# Works with any comment leader (#, //, ///, <!--, ...) — the directive token
# itself is what is matched. Check-ids are the keys of controls.CONTROLS.

_SUPPRESS_LINE_RE = re.compile(r"compliance-ignore:\s*([\w\-, ]+)")
_SUPPRESS_FILE_RE = re.compile(r"compliance-ignore-file:\s*([\w\-, ]+)")


def collect_suppressions(content):
    """Parse suppression directives out of file content.

    Returns (file_level: set[str], line_level: dict[int, set[str]]) where
    line numbers are 1-based and 'all' may appear in any set.
    """
    file_level = set()
    line_level = {}
    for i, line in enumerate(content.splitlines(), 1):
        m = _SUPPRESS_FILE_RE.search(line)
        if m:
            file_level.update(x.strip() for x in m.group(1).split(",") if x.strip())
            continue
        m = _SUPPRESS_LINE_RE.search(line)
        if m:
            ids = {x.strip() for x in m.group(1).split(",") if x.strip()}
            line_level.setdefault(i, set()).update(ids)
    return file_level, line_level


def is_suppressed(check_id, line_no, file_level, line_level):
    """True if check_id at line_no is silenced by a suppression directive.

    A line-level directive applies to its own line and the line directly below
    it (so a comment above the offending line works)."""
    if "all" in file_level or check_id in file_level:
        return True
    for directive_line in (line_no, line_no - 1):
        ids = line_level.get(directive_line)
        if ids and ("all" in ids or check_id in ids):
            return True
    return False


class PlatformComplianceVisitor(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.errors = []
        self.current_function = None

    def visit_FunctionDef(self, node):
        prev_func = self.current_function
        self.current_function = node
        
        # Invoke all registered FunctionDef AST checkers
        for checker in AST_FUNCTION_DEF_CHECKERS:
            checker(self, node)
            
        self.generic_visit(node)
        self.current_function = prev_func

    def visit_Call(self, node):
        # Invoke all registered Call AST checkers
        for checker in AST_CALL_CHECKERS:
            checker(self, node)
            
        self.generic_visit(node)

    def visit_Assign(self, node):
        # Invoke all registered Assign AST checkers
        for checker in AST_ASSIGN_CHECKERS:
            checker(self, node)
            
        self.generic_visit(node)

# Registry lists
AST_FUNCTION_DEF_CHECKERS = []
AST_CALL_CHECKERS = []
AST_ASSIGN_CHECKERS = []
FILE_CHECKERS = []

def register_ast_function_def(func):
    AST_FUNCTION_DEF_CHECKERS.append(func)
    return func

def register_ast_call(func):
    AST_CALL_CHECKERS.append(func)
    return func

def register_ast_assign(func):
    AST_ASSIGN_CHECKERS.append(func)
    return func

def register_file_checker(func):
    FILE_CHECKERS.append(func)
    return func
