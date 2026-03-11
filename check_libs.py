import importlib

libs = ["PyPDF2", "docx", "ebooklib", "mobi", "pypdf"]
for lib in libs:
    try:
        importlib.import_module(lib)
        print(f"{lib}: INSTALLED")
    except ImportError:
        print(f"{lib}: MISSING")
