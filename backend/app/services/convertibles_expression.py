"""Bounded arithmetic formulas for CB research. No eval, exec, imports or objects."""
from __future__ import annotations

import ast
import math
import operator
from functools import lru_cache


class FormulaError(ValueError):
    pass


class MissingInputError(ValueError):
    def __init__(self, names):
        self.names = sorted(set(names))
        super().__init__('缺少输入：' + '、'.join(self.names))


_BASE_FUNCTIONS = {'abs': abs, 'min': min, 'max': max, 'sqrt': math.sqrt,
                   'log': math.log, 'exp': math.exp, 'round': round}
_FINANCIAL_FUNCTIONS = {'pv', 'irr', 'put_irr', 'bs_call', 'cf_amount', 'cf_days', 'cf_count'}
_FUNCTIONS = set(_BASE_FUNCTIONS) | _FINANCIAL_FUNCTIONS | {'if', 'coalesce'}
_ALLOWED = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.BinOp, ast.UnaryOp,
            ast.Call, ast.Compare, ast.BoolOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
            ast.Pow, ast.Mod, ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or, ast.Eq,
            ast.NotEq, ast.Gt, ast.GtE, ast.Lt, ast.LtE)
_COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Gt: operator.gt,
            ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FormulaError('计算需要数值输入')
    value = float(value)
    if not math.isfinite(value) or abs(value) > 1e18:
        raise FormulaError('结果非有限数或超出数值范围')
    return value


@lru_cache(maxsize=256)
def _parse(expression, available):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 512:
        raise FormulaError('公式须为1至512个字符')
    # IF is a function in the editor, not Python's conditional statement.
    import re
    source = re.sub(r'\bIF\s*\(', 'ifelse(', expression, flags=re.I).replace('^', '**')
    try:
        tree = ast.parse(source, mode='eval')
    except (SyntaxError, ValueError, RecursionError):
        raise FormulaError('公式语法不正确') from None
    nodes = list(ast.walk(tree))
    if len(nodes) > 128:
        raise FormulaError('公式过于复杂，最多128个语法节点')
    names = set()
    for node in nodes:
        if not isinstance(node, _ALLOWED):
            raise FormulaError('只允许算术、比较及已列出的函数')
        if isinstance(node, ast.Constant) and node.value is not None and not isinstance(node.value, (int, float, bool)):
            raise FormulaError('公式不允许字符串或对象')
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.keywords or len(node.args) > 8:
                raise FormulaError('函数调用格式不受支持')
            name = node.func.id.lower()
            if name not in _FUNCTIONS | {'ifelse'}:
                raise FormulaError('未支持的函数：' + node.func.id)
        elif isinstance(node, ast.Name):
            if node.id.lower() in _FUNCTIONS | {'ifelse'}:
                continue
            if node.id not in available:
                raise FormulaError('未知变量：' + node.id)
            names.add(node.id)
    return tree, tuple(sorted(names))


def _evaluate(node, values, functions):
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, values, functions)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        value = values.get(node.id)
        if value is None:
            raise MissingInputError([node.id])
        return _number(value)
    if isinstance(node, ast.Call):
        name = node.func.id.lower()
        if name == 'ifelse':
            if len(node.args) != 3:
                raise FormulaError('IF需要条件、成立值、不成立值')
            branch = 1 if _evaluate(node.args[0], values, functions) else 2
            return _evaluate(node.args[branch], values, functions)
        if name == 'coalesce':
            if not node.args:
                raise FormulaError('COALESCE至少需要一个参数')
            missing = []
            for arg in node.args:
                try:
                    value = _evaluate(arg, values, functions)
                    if value is not None:
                        return value
                except MissingInputError as exc:
                    missing.extend(exc.names)
            raise MissingInputError(missing or ['coalesce'])
        if name not in functions:
            raise FormulaError('函数在当前计算中不可用：' + name)
        args = [_number(_evaluate(arg, values, functions)) for arg in node.args]
        if name == 'round' and len(args) == 2:
            if not args[1].is_integer() or not 0 <= args[1] <= 8:
                raise FormulaError('ROUND小数位须为0至8的整数')
            args[1] = int(args[1])
        return _number(functions[name](*args))
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, values, functions)
        if isinstance(node.op, ast.Not):
            return not value
        number = _number(value)
        return _number(-number if isinstance(node.op, ast.USub) else number)
    if isinstance(node, ast.BinOp):
        left = _number(_evaluate(node.left, values, functions))
        right = _number(_evaluate(node.right, values, functions))
        if isinstance(node.op, ast.Pow):
            if abs(right) > 20:
                raise FormulaError('幂指数绝对值不能大于20')
            return _number(left ** right)
        operation = {ast.Add: lambda: left + right, ast.Sub: lambda: left - right,
                     ast.Mult: lambda: left * right, ast.Div: lambda: left / right,
                     ast.Mod: lambda: left % right}
        return _number(operation[type(node.op)]())
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, values, functions)
        for op, other in zip(node.ops, node.comparators, strict=True):
            right = _evaluate(other, values, functions)
            if not _COMPARE[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        for arg in node.values:
            result = bool(_evaluate(arg, values, functions))
            if isinstance(node.op, ast.And) and not result:
                return False
            if isinstance(node.op, ast.Or) and result:
                return True
        return isinstance(node.op, ast.And)
    raise FormulaError('不支持的公式')


def evaluate_formulas(formulas: dict[str, str], inputs: dict, helpers: dict | None = None):
    """Validate all expressions and cycles before returning any personal result."""
    if len(formulas) > 32 or len(inputs) > 128:
        raise FormulaError('公式或参数数量超限')
    available = tuple(sorted(set(inputs) | set(formulas)))
    parsed = {key: _parse(expr, available) for key, expr in formulas.items()}
    order, visiting, done = [], set(), set()
    def visit(key):
        if key in visiting:
            raise FormulaError('公式存在循环依赖：' + key)
        if key in done:
            return
        visiting.add(key)
        for dependency in parsed[key][1]:
            if dependency in formulas:
                visit(dependency)
        visiting.remove(key)
        done.add(key)
        order.append(key)
    for key in formulas:
        visit(key)
    functions = {**_BASE_FUNCTIONS, **(helpers or {})}
    if set(functions) - (set(_BASE_FUNCTIONS) | _FINANCIAL_FUNCTIONS):
        raise FormulaError('未注册的计算函数')
    values, result = dict(inputs), {}
    for key in order:
        tree, dependencies = parsed[key]
        detail = {'formula': formulas[key], 'inputs': {n: values.get(n) for n in dependencies},
                  'result': None, 'status': 'ok', 'missing': [], 'error': None}
        try:
            detail['result'] = _number(_evaluate(tree, values, functions))
        except MissingInputError as exc:
            detail.update(status='missing', missing=exc.names)
        except (FormulaError, ValueError, OverflowError, ZeroDivisionError, TypeError):
            detail.update(status='error', error='计算失败，请检查公式、数值范围与定义域')
        values[key] = detail['result']
        result[key] = detail
    return result
