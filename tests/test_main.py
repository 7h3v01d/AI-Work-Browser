"""
Smoke tests for main.py.

main() itself calls sys.exit(app.exec()) and would block/exit the test
process, so it is intentionally not called here. These tests just confirm
the module imports cleanly and its stylesheet constant is sane.
"""

import main


def test_module_imports_without_side_effects():
    assert hasattr(main, "main")
    assert callable(main.main)


def test_base_stylesheet_is_non_empty_qss():
    css = main._BASE_STYLESHEET
    assert isinstance(css, str)
    assert "QMainWindow" in css
    assert "QLineEdit" in css
    assert "{" in css and "}" in css
