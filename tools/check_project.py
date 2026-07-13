import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"


def check_python_syntax() -> list[str]:
    errors = []

    for path in APP_DIR.rglob("*.py"):
        try:
            compile(
                path.read_text(encoding="utf-8"),
                str(path),
                "exec",
            )
        except SyntaxError as error:
            errors.append(f"{path}: {error}")

    return errors


def check_main_window_methods() -> list[str]:
    path = APP_DIR / "ui" / "main_window.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    main_window = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "MainWindow"
        ),
        None,
    )

    if main_window is None:
        return ["MainWindowクラスがありません。"]

    method_names = {
        node.name
        for node in main_window.body
        if isinstance(node, ast.FunctionDef)
    }

    required = {
        "__init__",
        "_build_ui",
        "_build_sidebar",
        "_build_pages",
        "_connect_navigation",
        "open_settings_app",
    }

    missing = sorted(required - method_names)
    return [
        f"MainWindowに必要なメソッドがありません: {name}"
        for name in missing
    ]


def main():
    errors = []
    errors.extend(check_python_syntax())
    errors.extend(check_main_window_methods())

    if errors:
        print("プロジェクトチェック: NG")
        for error in errors:
            print("-", error)
        raise SystemExit(1)

    print("プロジェクトチェック: OK")
    print("・全Pythonファイル構文OK")
    print("・MainWindow必須メソッドOK")


if __name__ == "__main__":
    main()
