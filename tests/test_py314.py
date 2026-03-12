import sys

print(f"Version: {sys.version}")
print(f"Free-threaded supported in build: {hasattr(sys, '_is_free_threaded')}")
if hasattr(sys, '_is_free_threaded'):
    print(f"Is currently free-threaded: {sys._is_free_threaded()}")

# Testing t-string syntax (PEP 750)
try:
    # In Python 3.14, t-strings should be available
    # Usage: t"hello {world}"
    world = "world"
    # Testing if parser accepts 't' prefix
    # Note: Using eval to avoid syntax error in 3.11 if I were running this script in 3.11
    # But since I intend to run this in 3.14, I'll just write it.
    
    class TestTag:
        def __call__(self, *args, **kwargs):
            return "t-string works!"
    
    # Python 3.14 t-string syntax
    # t"template {variable}"
    # Actually, PEP 750 mentions 't' as a built-in or custom tag.
    # Let's try it simply.
    code = 'def test(): return t"test"'
    exec(code)
    print("t-string syntax check: PASSED (exec)")
except SyntaxError:
    print("t-string syntax check: FAILED (SyntaxError)")
except NameError:
    print("t-string syntax check: PARTIAL (Syntax works, but 't' tag not defined)")
except Exception as e:
    print(f"t-string syntax check: ERROR ({type(e).__name__}: {e})")
