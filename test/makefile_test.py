import os
from pathlib import Path
import subprocess
import tempfile


def test_desktop_targets():
    makefile = (Path(__file__).resolve().parents[1] / 'Makefile').read_text()
    with tempfile.TemporaryDirectory(prefix='run test ') as directory:
        root = Path(directory)
        (root / 'Makefile').write_text(makefile)
        commands = root / 'bin'
        commands.mkdir()
        for name, body in {
            'uname': 'echo "$MOCK_OS"',
            'flutter': 'if [[ "$*" == *linux* ]]; then test ! -e build/linux/x64/release/CMakeCache.txt || exit 1; fi\nprintf "<%s>\\n" "$@"\nexit "${MOCK_EXIT:-0}"',
        }.items():
            command = commands / name
            command.write_text('#!/usr/bin/env bash\n' + body + '\n')
            command.chmod(0o755)
        for goal, host, override, target in [
            (goal, host, override, target)
            for goal in ['run', 'build']
            for host, override, target in [
                ('Darwin', 'auto', 'macos'), ('Linux', 'auto', 'linux'),
                ('MINGW64_NT', 'auto', 'windows'), ('unknown', 'auto', None),
                ('Darwin', 'linux', 'linux'), ('Darwin', 'invalid', None),
            ]
        ]:
            caches = [root / f'build/linux/{path}/CMakeCache.txt' for path in [
                'x64/debug', 'x64/release', 'arm64/profile',
            ]]
            for cache in caches:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text('mpv_INCLUDEDIR:INTERNAL=/tmp/kuraku-linux-deps/root/usr/include\n')
            artifact = caches[1].with_name('keep.o')
            artifact.write_text('keep')
            result = subprocess.run(
                ['make', '--no-print-directory', '-C', str(root), goal, f'TARGET={override}',
                 'ARGS=--release --dart-define="LABEL=hello world"'],
                env={**os.environ, 'PATH': f'{commands}:{os.environ["PATH"]}', 'MOCK_OS': host},
                capture_output=True, text=True,
            )
            assert (result.returncode == 0) == (target is not None), result.stderr
            assert all(cache.exists() == (target != 'linux') for cache in caches)
            assert artifact.read_text() == 'keep'
            if target:
                command = f'<run>\n<-d>\n<{target}>\n' if goal == 'run' else (
                    f'<build>\n<{target}>\n<--release>\n')
                assert result.stdout == command + '<--release>\n<--dart-define=LABEL=hello world>\n'
            else:
                assert ('Invalid TARGET' if override == 'invalid' else 'Unsupported OS') in result.stderr
        result = subprocess.run(
            ['make', '--no-print-directory', '-C', str(root), 'run'],
            env={**os.environ, 'PATH': f'{commands}:{os.environ["PATH"]}', 'MOCK_OS': 'Darwin', 'MOCK_EXIT': '7'},
            capture_output=True, text=True,
        )
        assert result.returncode != 0


def test_helper_targets():
    makefile = (Path(__file__).resolve().parents[1] / 'Makefile').read_text()
    with tempfile.TemporaryDirectory(prefix='make helpers test ') as directory:
        root = Path(directory)
        (root / 'Makefile').write_text(makefile)
        commands = root / 'bin'
        commands.mkdir()
        log = root / 'calls'
        for name in ['flutter', 'dart', 'nice']:
            command = commands / name
            body = 'shift 2\nexec "$@"' if name == 'nice' else 'exit "${MOCK_EXIT:-0}"'
            command.write_text(f'#!/usr/bin/env bash\necho "{name} $*" >> "$CALL_LOG"\n{body}\n')
            command.chmod(0o755)
        environment = {**os.environ, 'PATH': f'{commands}:{os.environ["PATH"]}', 'CALL_LOG': str(log)}
        for arguments, expected in [
            ([], []), (['help'], []),
            (['deps'], ['flutter pub get --enforce-lockfile']),
            (['env'], ['dart run enven']),
            (['analyze', 'ARGS=--fatal-infos'], ['flutter analyze --no-pub --fatal-infos']),
            (['doctor'], ['flutter doctor -v']),
            (['clean'], ['flutter clean']),
            (['test', 'TEST=test/a test.dart', 'ARGS=--reporter expanded'], [
                'nice -n 10 flutter test --no-pub --concurrency=1 test/a test.dart --reporter expanded',
                'flutter test --no-pub --concurrency=1 test/a test.dart --reporter expanded',
            ]),
            (['test'], []),
        ]:
            log.write_text('')
            result = subprocess.run(
                ['make', '--no-print-directory', '-C', str(root), *arguments],
                env=environment, capture_output=True, text=True,
            )
            assert (result.returncode == 0) == (arguments != ['test']), result.stderr
            assert log.read_text().splitlines() == expected
            if not arguments or arguments == ['help']:
                for target in ['run', 'install', 'deps', 'env', 'build', 'analyze', 'test', 'doctor', 'clean']:
                    assert f'  {target:<10} ' in result.stdout
        result = subprocess.run(
            ['make', '--no-print-directory', '-C', str(root), 'test', 'TEST=test/example.dart'],
            env={**environment, 'MOCK_EXIT': '7'}, capture_output=True, text=True,
        )
        assert result.returncode != 0


def test_install():
    script = (Path(__file__).resolve().parents[1] / 'Makefile').read_text()
    with tempfile.TemporaryDirectory(prefix='install test ') as directory:
        root = Path(directory)
        apps = root / 'Applications'
        apps.mkdir()
        script = script.replace('/Applications', str(apps))
        # Quote the directory check too, since the test path contains spaces.
        script = script.replace(f'[ -w {apps} ]', f'[ -w "{apps}" ]')
        (root / 'Makefile').write_text(script)
        commands = root / 'bin'
        commands.mkdir()
        mocks = {
            'dart': 'exit 0',
            'git': 'echo "${COMMIT_COUNT:-1}"',
            'date': 'echo 20261008',
            'flutter': '''
if [ "$1" = build ]; then
  if [ "$2" = linux ]; then test ! -e build/linux/x64/release/CMakeCache.txt; fi
  echo "$*" >> "$CALL_LOG"
  [ "$SCENARIO" != build_failure ] || exit 1
  if [ "$SCENARIO" != missing_bundle ]; then
    mkdir -p build/macos/Build/Products/Release/KuraKu.app
  fi
fi
''',
            'ditto': '''
echo copy >> "$CALL_LOG"
[ "$SCENARIO" != copy_failure ] || exit 1
mkdir -p "$2"
''',
            'sudo': 'echo sudo >> "$CALL_LOG"\nexec "$@"',
        }
        for name, body in mocks.items():
            command = commands / name
            command.write_text('#!/usr/bin/env bash\nset -e\n' + body + '\n')
            command.chmod(0o755)

        for scenario in ['missing_bundle', 'build_failure', 'copy_failure', 'success', 'needs_sudo', 'repeat', 'new_day', 'invalid_version', 'future_date', 'invalid_count']:
            version = {
                'repeat': '1.2.3+20261008.59',
                'new_day': '1.2.3+20261007.59',
                'invalid_version': 'invalid',
                'future_date': '1.2.3+20261009.1',
            }.get(scenario, '1.0.0+1')
            original = f'name: kuraku\nversion: {version}\n# keep this comment\n'
            (root / 'pubspec.yaml').write_text(original)
            env_content = "APP_NAME='kuraku'\n"
            (root / '.env').write_text(env_content)
            log = root / 'calls'
            log.write_text('')
            apps.chmod(0o555 if scenario == 'needs_sudo' else 0o755)
            result = subprocess.run(
                ['make', '--no-print-directory', '-C', str(root), 'install', 'TARGET=macos'],
                env={**os.environ, 'PATH': f'{commands}:{os.environ["PATH"]}',
                     'SCENARIO': scenario, 'CALL_LOG': str(log),
                     'COMMIT_COUNT': 'invalid' if scenario == 'invalid_count' else '1'},
                capture_output=True, text=True,
            )
            assert (result.returncode == 0) == (scenario in ['success', 'needs_sudo', 'repeat', 'new_day']), result.stderr
            calls = log.read_text().splitlines()
            assert ('copy' in calls) == (scenario in ['copy_failure', 'success', 'needs_sudo', 'repeat', 'new_day'])
            assert ('sudo' in calls) == (scenario == 'needs_sudo' and not os.access(apps, os.W_OK))
            assert ('Installed:' in result.stdout) == (result.returncode == 0)
            assert (root / '.env').read_text() == env_content
            assert not list(root.glob('pubspec.yaml.*'))
            if scenario in ['missing_bundle', 'build_failure', 'copy_failure', 'invalid_version', 'future_date', 'invalid_count']:
                assert (root / 'pubspec.yaml').read_text() == original
            else:
                expected = '1.2.3+20261008.60' if scenario == 'repeat' else (
                    '1.2.3+20261008.1' if scenario == 'new_day' else '1.0.0+20261008.1')
                assert (root / 'pubspec.yaml').read_text() == original.replace(version, expected)
                name, number = expected.split('+')
                assert f'build macos --release --build-name={name} --build-number={number}' in calls
            apps.chmod(0o755)

        (root / 'tool').mkdir()
        (root / 'tool/package_linux.sh').write_text('echo "package $1" >> "$CALL_LOG"\n')
        (root / 'pubspec.yaml').write_text('name: kuraku\nversion: 1.0.0+1\n')
        cache = root / 'build/linux/x64/release/CMakeCache.txt'
        cache.parent.mkdir(parents=True)
        cache.write_text('mpv_INCLUDEDIR:INTERNAL=/tmp/kuraku-linux-deps/root/usr/include\n')
        log.write_text('')
        result = subprocess.run(
            ['make', '--no-print-directory', '-C', str(root), 'install', 'TARGET=linux'],
            env={**os.environ, 'PATH': f'{commands}:{os.environ["PATH"]}',
                 'SCENARIO': 'success', 'CALL_LOG': str(log)},
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert not cache.exists()
        assert 'build linux --release' in log.read_text()
        assert 'package 1.0.0+20261008.1' in log.read_text()


if __name__ == '__main__':
    test_desktop_targets()
    test_helper_targets()
    test_install()
    print('Makefile checks passed')
