"""Simple runner that executes all test_* functions across test modules."""

import sys
import traceback

import tests.test_soe_ddci as mod
import tests.test_lgc as lgc_mod


def collect(module):
    return [
        (name, fn)
        for name, fn in vars(module).items()
        if name.startswith("test_") and callable(fn)
    ]


def main() -> int:
    funcs = collect(mod) + collect(lgc_mod)
    passed = failed = 0
    for name, fn in funcs:
        try:
            fn()
            print(f"PASS  {name}")
            passed += 1
        except Exception:
            print(f"FAIL  {name}")
            traceback.print_exc()
            failed += 1
    print("-" * 60)
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())