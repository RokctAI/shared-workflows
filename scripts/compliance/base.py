import ast

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
