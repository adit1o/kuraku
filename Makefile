SHELL := bash
TARGET ?= auto
export TARGET

.DEFAULT_GOAL := help
.PHONY: help run install deps env build analyze test doctor clean

help: ## Show available commands
	@awk 'BEGIN { print "Usage: make <target> [VARIABLE=value]\n" } /^[a-z]+:.*## / { split($$0, parts, "## "); sub(/:.*/, "", parts[1]); printf "  %-10s %s\n", parts[1], parts[2] }' $(MAKEFILE_LIST)
	@printf '\nOptions:\n  TARGET=auto|macos|linux|windows\n  TEST=test/affected_test.dart (required for test)\n  ARGS="..." (extra Flutter arguments for run, build, analyze, test)\n'

deps: ## Fetch locked Flutter dependencies
	flutter pub get --enforce-lockfile

env: ## Generate embedded configuration from .env
	dart run enven

analyze: ## Run static analysis without fetching dependencies
	flutter analyze --no-pub $(ARGS)

test: ## Run the test file or directory specified by TEST, sequentially
	@test -n "$(TEST)" || { echo 'Usage: make test TEST=test/affected_test.dart' >&2; exit 1; }
	@if command -v nice >/dev/null 2>&1; then \
		nice -n 10 flutter test --no-pub --concurrency=1 "$(TEST)" $(ARGS); \
	else \
		flutter test --no-pub --concurrency=1 "$(TEST)" $(ARGS); \
	fi

doctor: ## Diagnose Flutter and platform tooling
	flutter doctor -v

clean: ## Remove Flutter build artifacts (run deps afterward)
	flutter clean

run: ## Run the app on the host OS
build: ## Build a release without installation or version changes

run build:
	@set -Eeuo pipefail; \
	target="$$TARGET"; \
	case "$$target" in \
		auto) \
			case "$$(uname -s)" in \
				Darwin) target=macos ;; \
				Linux) target=linux ;; \
				MINGW*|MSYS*|CYGWIN*|Windows_NT) target=windows ;; \
				*) echo 'Unsupported OS' >&2; exit 1 ;; \
			esac ;; \
		macos|linux|windows) ;; \
		*) echo 'Invalid TARGET: use auto, macos, linux, or windows' >&2; exit 1 ;; \
	esac; \
	if [ "$$target" = linux ]; then rm -f build/linux/*/*/CMakeCache.txt; fi; \
	if [ '$@' = run ]; then \
		exec flutter run -d "$$target" $(ARGS); \
	else \
		exec flutter build "$$target" --release $(ARGS); \
	fi

install: ## Build and install (macOS) or package (Linux/Windows), then save the build version
	@set -Eeuo pipefail; \
	log() { echo "==> $$1"; }; \
	fail() { echo "ERROR: $$1" >&2; exit 1; }; \
	require_command() { command -v "$$1" >/dev/null 2>&1 || fail "Missing command: $$1"; }; \
	require_command dart; \
	require_command flutter; \
	require_command git; \
	[ -f pubspec.yaml ] || fail 'pubspec.yaml not found'; \
	[ -f .env ] || fail '.env not found'; \
	case "$$TARGET" in \
		auto|macos|windows|linux) ;; \
		*) fail 'Usage: make install [TARGET=auto|macos|windows|linux]' ;; \
	esac; \
	resolved_target="$$TARGET"; \
	if [ "$$resolved_target" = auto ]; then \
		case "$$(uname -s)" in \
			Darwin) resolved_target=macos ;; \
			Linux) resolved_target=linux ;; \
			MINGW*|MSYS*|CYGWIN*|Windows_NT) resolved_target=windows ;; \
			*) fail "Unsupported OS: $$(uname -s). Run with explicit target if needed." ;; \
		esac; \
	fi; \
	current_version="$$(awk '/^version:/ {print $$2; exit}' pubspec.yaml)"; \
	[ -n "$$current_version" ] || fail 'Cannot read version from pubspec.yaml'; \
	[[ "$$current_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(\+[0-9]+(\.[0-9]+)?)?$$ ]] || fail "Invalid version: $$current_version"; \
	base_version="$${current_version%%+*}"; \
	build_date="$$(date '+%Y%m%d')"; \
	build_sequence="$$(git rev-list --count HEAD)"; \
	[[ "$$build_sequence" =~ ^[0-9]+$$ ]] || fail 'Cannot read commit count'; \
	build_sequence=$$((10#$$build_sequence)); \
	if [[ "$$current_version" =~ \+([0-9]{8})\.([0-9]+)$$ ]]; then \
		previous_date="$${BASH_REMATCH[1]}"; \
		previous_sequence=$$((10#$${BASH_REMATCH[2]})); \
		[[ "$$build_date" < "$$previous_date" ]] && fail 'Build date is older than the current version'; \
		if [ "$$build_date" = "$$previous_date" ] && [ "$$build_sequence" -le "$$previous_sequence" ]; then \
			build_sequence=$$((previous_sequence + 1)); \
		fi; \
	fi; \
	build_number="$${build_date}.$${build_sequence}"; \
	new_version="$${base_version}+$${build_number}"; \
	log "Build version: $$current_version -> $$new_version"; \
	tmp_pubspec="$$(mktemp pubspec.yaml.XXXXXX)"; \
	trap 'rm -f "$$tmp_pubspec"' EXIT; \
	awk -v current="$$current_version" -v newver="$$new_version" \
		'$$1 == "version:" && $$2 == current { print "version: " newver; done = 1; next } { print } END { if (done != 1) exit 1 }' \
		pubspec.yaml > "$$tmp_pubspec" || fail 'Failed to update version in pubspec.yaml'; \
	log 'Generate secure env'; \
	dart run enven; \
	log 'Refresh dependencies'; \
	flutter pub get; \
	log "Build KuraKu for $$resolved_target"; \
	if [ "$$resolved_target" = linux ]; then rm -f build/linux/*/*/CMakeCache.txt; fi; \
	flutter build "$$resolved_target" --release --build-name="$$base_version" --build-number="$$build_number"; \
	case "$$resolved_target" in \
		macos) \
			log 'Output: build/macos/Build/Products/Release'; \
			app_bundle='build/macos/Build/Products/Release/KuraKu.app'; \
			installed_app='/Applications/KuraKu.app'; \
			[ -d "$$app_bundle" ] || fail "App bundle not found: $$app_bundle"; \
			require_command ditto; \
			log "Install KuraKu: $$installed_app"; \
			if [ -w /Applications ] && { [ ! -e "$$installed_app" ] || [ -w "$$installed_app" ]; }; then \
				ditto "$$app_bundle" "$$installed_app"; \
			else \
				require_command sudo; \
				sudo ditto "$$app_bundle" "$$installed_app"; \
			fi; \
			log "Installed: $$installed_app"; \
			;; \
		linux) \
			bash tool/package_linux.sh "$$new_version"; \
			;; \
		windows) \
			powershell.exe -NoProfile -ExecutionPolicy Bypass -File tool/package_windows.ps1 -Version "$$new_version"; \
			;; \
	esac; \
	mv "$$tmp_pubspec" pubspec.yaml; \
	log "Saved version: $$new_version"; \
	log 'Clean compile cache'; \
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +; \
	log Done
