"""api/deploy.sh zips a fixed list of files for the gandw-api Lambda. A module the API imports
but the list leaves out works locally and in CI, then crashes the live Lambda on import.
This keeps the list complete.  python -m unittest discover -s api"""
import ast
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def local_imports(name, seen=None):
    """Every module in api/ that `name` imports, directly or through another api/ module."""
    seen = set() if seen is None else seen
    src = open(os.path.join(HERE, name + ".py"), encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
               [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
        for m in mods:
            m = m.split(".")[0]
            if m not in seen and os.path.exists(os.path.join(HERE, m + ".py")):
                seen.add(m)
                local_imports(m, seen)
    return seen


class DeployListTest(unittest.TestCase):
    def test_every_module_the_api_imports_is_shipped(self):
        script = open(os.path.join(HERE, "deploy.sh"), encoding="utf-8").read()
        shipped = set(re.findall(r'"(\w+)\.py"', script))
        needed = local_imports("app") | {"app"}
        self.assertEqual(sorted(needed - shipped), [], "add these to the zip list in api/deploy.sh")


if __name__ == "__main__":
    unittest.main()
