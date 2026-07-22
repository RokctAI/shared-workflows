import ast
import os
from compliance.base import register_file_checker

@register_file_checker
def check_layer18_ztna_mtls(filepath):
    errors = []
    base = os.path.basename(filepath).lower()
    path_lower = filepath.lower()
    if "test" in path_lower:
        return errors
    if filepath.endswith(".py"):
        if any(x in base for x in ["auth", "login", "gateway", "api"]):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                # Enforce zero trust checks like headers, certs, token verification, mTLS
                if not any(x in content.lower() for x in ["cert", "mtls", "tls", "token", "jwt", "verify", "permission", "authorized"]):
                    errors.append({
                        "line": 1,
                        "type": "Layer 18 (ZTNA & mTLS)",
                        "message": f"Auth/API module '{os.path.basename(filepath)}' fails to enforce Zero Trust authorization policies or mTLS certificate checks."
                    })
            except Exception as e:
                errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

@register_file_checker
def check_layer18_path_traversal(filepath):
    errors = []
    if filepath.endswith(".py"):
        base = os.path.basename(filepath).lower()
        if "test" in base:
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # If path joining is done, check for containment validation checks like is_safe_path
            if "os.path.join" in content and not any(x in content for x in ["is_safe_path", "abspath", "startswith"]):
                errors.append({
                    "line": 1,
                    "type": "Layer 18 (ZTNA & path containment checks)",
                    "message": f"Module '{os.path.basename(filepath)}' uses path join/manipulation without validating containment boundaries (e.g. verifying paths start with expected base directory)."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

@register_file_checker
def check_layer18_command_injection(filepath):
    errors = []
    if filepath.endswith(".py"):
        base = os.path.basename(filepath).lower()
        if "test" in base or "compliance" in filepath.replace("\\", "/").lower():
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # Enforce that shell=True is avoided when running commands
            if "subprocess.run" in content and "shell=True" in content:
                errors.append({
                    "line": 1,
                    "type": "Layer 18 (Process execution security hardening)",
                    "message": f"Module '{os.path.basename(filepath)}' uses subprocess.run with shell=True which exposes the system to shell metacharacter command injection."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

# ── Generic global-mutable-state thread-safety analysis ──────────────────────
#
# Replaces an earlier version that only recognised three literal global names
# (ACTIVE_TOKENS, PR_COMMENTS, PR_NUMBERS_TO_BRANCHES) from one specific script,
# and "verified" locking with a substring test for "Lock()" anywhere in the file.
# This version works on any Python file: it finds module-level mutable globals
# via AST, finds the statements that actually mutate them, and reports only
# mutations that are not lexically inside a lock-like `with` block.
#
# Scope limit (deliberate, documented rather than hidden): this is lexical, not
# a data-flow analysis. Aliasing (`d = MY_GLOBAL; d[k] = v`) and mutations made
# through a helper that receives the global as an argument are not detected.
# Full inter-procedural data-flow was judged not worth the cost here; the common
# real-world shape — a module-level dict mutated directly by request/thread
# handlers — is caught.

_MUTATING_METHODS = {
    "append", "extend", "insert", "pop", "popitem", "remove", "clear",
    "update", "setdefault", "add", "discard", "sort", "appendleft", "popleft",
}

_MUTABLE_FACTORIES = {
    "dict", "list", "set", "defaultdict", "OrderedDict", "deque", "Counter",
}


def _module_level_mutable_globals(tree):
    """Module-scope names bound to a mutable container literal or factory call."""
    found = {}
    for node in tree.body:
        targets, value = [], None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        is_mutable = isinstance(value, (ast.Dict, ast.List, ast.Set))
        if isinstance(value, ast.Call):
            fn = value.func
            fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if fname in _MUTABLE_FACTORIES:
                is_mutable = True
        if is_mutable:
            for t in targets:
                if isinstance(t, ast.Name):
                    found[t.id] = node.lineno
    return found


_LOCK_FACTORIES = ("Lock", "RLock", "Semaphore", "BoundedSemaphore", "Condition")


def _lock_names(tree):
    """Module-level names bound to a lock object, e.g. `_guard = threading.Lock()`.

    Resolving the binding (rather than only pattern-matching the variable name)
    means `with _guard:` is recognised as a lock even though nothing in the
    identifier says "lock".
    """
    names = set()
    for node in ast.walk(tree):
        targets, value = [], None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if not isinstance(value, ast.Call):
            continue
        fn = value.func
        fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        if fname in _LOCK_FACTORIES:
            for t in targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
                elif isinstance(t, ast.Attribute):
                    names.add(t.attr)
    return names


def _is_lock_context(expr, known_locks=frozenset()):
    """True if a `with` context expression is (or looks like) a lock."""
    if isinstance(expr, ast.Call):
        expr = expr.func
    name = ""
    if isinstance(expr, ast.Name):
        name = expr.id
    elif isinstance(expr, ast.Attribute):
        name = expr.attr
    if name in known_locks:
        return True
    lowered = name.lower()
    return any(k in lowered for k in ("lock", "mutex", "semaphore"))


def _globals_declared(tree):
    """Names appearing in any `global X` statement (rebinding, not just mutating)."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            names.update(node.names)
    return names


def _mutation_target(node, tracked, rebound):
    """If `node` mutates a tracked global, return its name — else None."""
    # NAME[k] = v  /  NAME[k] += v  /  del NAME[k]
    subscript_targets = []
    if isinstance(node, ast.Assign):
        subscript_targets = node.targets
    elif isinstance(node, (ast.AugAssign, ast.Delete)):
        subscript_targets = node.targets if isinstance(node, ast.Delete) else [node.target]
    for t in subscript_targets:
        if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id in tracked:
            return t.value.id
        # Plain rebinding only counts when the function declared `global NAME`
        if isinstance(t, ast.Name) and t.id in tracked and t.id in rebound:
            return t.id
    # NAME.append(...) / NAME.update(...) / ...
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in _MUTATING_METHODS:
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id in tracked:
                return owner.id
    return None


def _collect_unguarded(node, tracked, rebound, guarded, out, known_locks=frozenset()):
    for child in ast.iter_child_nodes(node):
        child_guarded = guarded
        if isinstance(child, (ast.With, ast.AsyncWith)):
            if any(_is_lock_context(item.context_expr, known_locks) for item in child.items):
                child_guarded = True
        if not child_guarded:
            name = _mutation_target(child, tracked, rebound)
            if name and name not in out:
                out[name] = child.lineno
        _collect_unguarded(child, tracked, rebound, child_guarded, out, known_locks)


@register_file_checker
def check_layer18_thread_safety(filepath):
    """Flag module-level mutable globals mutated without a lock in concurrent code."""
    errors = []
    if not filepath.endswith(".py"):
        return errors
    base = os.path.basename(filepath).lower()
    if "test" in base:
        return errors
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Only meaningful where concurrency actually exists.
        concurrent = any(x in content for x in [
            "threading", "concurrent.futures", "ThreadPoolExecutor",
            "fastapi", "FastAPI", "flask", "Flask", "multiprocessing.pool",
        ])
        if not concurrent:
            return errors

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return errors

        tracked = _module_level_mutable_globals(tree)
        if not tracked:
            return errors
        rebound = _globals_declared(tree)
        known_locks = _lock_names(tree)

        # Only inspect function bodies — module-level init runs single-threaded.
        unguarded = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _collect_unguarded(node, tracked, rebound, False, unguarded, known_locks)

        for name, lineno in sorted(unguarded.items(), key=lambda kv: kv[1]):
            errors.append({
                "line": lineno,
                "type": "Layer 18 (Thread Concurrency Safety)",
                "message": (
                    f"Global mutable state '{name}' (defined at line {tracked[name]} of "
                    f"'{os.path.basename(filepath)}') is mutated at line {lineno} without holding a "
                    f"lock, in a module that uses threads/async workers. Guard the mutation with a "
                    f"'with <lock>:' block, or suppress with '# compliance-ignore: thread-safety' "
                    f"if this state is provably single-threaded."
                )
            })
    except Exception as e:
        errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

@register_file_checker
def check_layer18_background_task_logging(filepath):
    errors = []
    if filepath.endswith(".py"):
        base = os.path.basename(filepath).lower()
        if "test" in base:
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # Verify background thread targets use structured stderr/logging context to handle unexpected exceptions
            if "Thread(" in content and "target=" in content:
                if "sys.stderr.write" not in content and "logger.error" not in content and "except Exception" not in content:
                    errors.append({
                        "line": 1,
                        "type": "Layer 18 (Background Thread Exception Safety)",
                        "message": f"Module '{os.path.basename(filepath)}' launches background threads without structured catch-all logging blocks to capture failures on sys.stderr."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors
