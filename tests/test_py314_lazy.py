# Testing Deferred Evaluation of Annotations (PEP 649/749)
import sys

print(f"Testing on Python {sys.version}")

class Parent:
    # Child is defined AFTER Parent, but this should work in 3.14 natively
    def get_child(self) -> Child:
        return Child()

class Child:
    pass

# Checking annotations
annotations = Parent.get_child.__annotations__
print(f"Annotations for get_child: {annotations}")

# In 3.14, 'Child' should be evaluated lazily. 
# We can check if it's a string or a real type object.
# Actually, PEP 649 means it's stored in a way that can be evaluated when needed.

try:
    return_type = annotations['return']
    print(f"Return type type: {type(return_type)}")
    print(f"Return type value: {return_type}")
    
    if return_type is Child:
        print("Lazy Annotation (PEP 649) Check: PASSED (Evaluated to object)")
    else:
        print("Lazy Annotation (PEP 649) Check: FAILED (Evaluated to something else)")
except Exception as e:
    print(f"Lazy Annotation (PEP 649) Check: ERROR ({type(e).__name__}: {e})")
