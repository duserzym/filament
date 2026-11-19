# Development commands (see README "Development").
# PYTHONPATH is cleared so packages on the user's own path (for example
# UPbRPy's GUI) never leak into tests or builds.
PYTHON := env -u PYTHONPATH .venv/bin/python
# An explicit value (including "-") overrides automatic lab signing.
APPLE_SIGNING_IDENTITY ?= $(shell security find-certificate -c "UPb Lab Code Signing" >/dev/null 2>&1 && echo "UPb Lab Code Signing")
BUILD_ROOT := $(shell $(PYTHON) scripts/build_desktop.py --print-build-root 2>/dev/null)

.PHONY: test-quick test build clean-build install

test-quick:
	$(PYTHON) scripts/run_tests.py quick

test:
	$(PYTHON) scripts/run_tests.py full

# PyInstaller build outside the repository, then the frozen smoke test.
build:
	APPLE_SIGNING_IDENTITY="$(APPLE_SIGNING_IDENTITY)" $(PYTHON) scripts/build_desktop.py $(BUILD_ARGS)

# Verify a staged copy and atomically swap it into /Applications. Quit first.
install:
	$(PYTHON) scripts/install_desktop.py

# Remove PyInstaller output (work/ and dist/ under the build root) and ./build.
clean-build:
	@case "$(BUILD_ROOT)" in ""|/|"$(HOME)"|"$(HOME)/") echo "Unexpected build folder '$(BUILD_ROOT)'; not cleaning."; exit 1;; esac
	@if pgrep -f "build_desktop.py|PyInstaller|pyinstaller" >/dev/null; then echo "A build is running; not cleaning."; exit 1; fi
	@du -sh ./build "$(BUILD_ROOT)/work" "$(BUILD_ROOT)/dist" 2>/dev/null | sed 's/^/before: /' || true
	@df -h / | awk 'NR==2 {print "Free on /: " $$4 " (before)"}'
	rm -rf ./build ./dist "$(BUILD_ROOT)/work" "$(BUILD_ROOT)/dist"
	@df -h / | awk 'NR==2 {print "Free on /: " $$4 " (after)"}'
