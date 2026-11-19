import ast, re
content = open('dashboard/app.py', encoding='utf-8').read()
# Check if it parses with warning
try:
    ast.parse(content)
    print("Parses OK")
except SyntaxError as e:
    print("SyntaxError:", e)
