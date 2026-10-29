"""Run pytest with all standard fixtures and a meaningful exit status."""
import sys
import pytest
if __name__ == "__main__":
    raise SystemExit(pytest.main(sys.argv[1:] or ["tests"]))
