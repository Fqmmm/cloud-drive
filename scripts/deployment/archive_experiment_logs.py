"""Publish retained experiment logs without changing private originals or services."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
LAB = Path('D:/CloudDriveLab/E1Native')
TEXT_SUFFIXES = {'.log', '.json', '.jsonl', '.csv', '.txt', '.out', '.err'}


def sensitive_key(key):
    name = re.sub(r'[_-]', '', key.lower())
    return any(word in name for word in ['password', 'passwd', 'secret']) or name in {
        'token', 'accesstoken', 'refreshtoken', 'sharetoken', 'extractcode', 'extractioncode',
        'internalapitoken', 'authorization', 'miniorootuser', 'accesskey'}


class Redactor:
    def __init__(self, secrets=()):
        self.secrets = sorted({s for s in secrets if isinstance(s, str) and len(s) >= 6}, key=len, reverse=True)

    def structured(self, data):
        if isinstance(data, dict):
            return {key: '[REDACTED]' if sensitive_key(key) and isinstance(value, str) else self.structured(value)
                    for key, value in data.items()}
        if isinstance(data, list):
            return [self.structured(value) for value in data]
        return data

    def text(self, text):
        for value in self.secrets:
            if len(value) >= 12:
                text = text.replace(value, '[REDACTED]')
            else:
                # Preserve decimal IDs, timestamp fractions, hashes and UUID components.
                text = re.sub(r'(?<![A-Za-z0-9_.-])' + re.escape(value) + r'(?![A-Za-z0-9_.-])', '[REDACTED]', text)
        text = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED-JWT]', text)
        text = re.sub(r'(/s/)[A-Za-z0-9_-]{22}(?![A-Za-z0-9_-])', r'\1[REDACTED-SHARE]', text)
        text = re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9._~+/-]{12,}={0,2}', r'\1[REDACTED]', text)
        pattern = r'''(?i)(\b(?:password|passwd|jwt_secret|internal_api_token|x-internal-token|extract(?:ion)?code|sharetoken|accesskey)\b["']?\s*[:=]\s*["']?)([^\s"'&,}\]]+)'''
        return re.sub(pattern, lambda m: m[0] if m[2].startswith('[REDACTED') else m[1] + '[REDACTED]', text)


def secret_values():
    values = set()

    def collect(data):
        if isinstance(data, dict):
            for key, value in data.items():
                if sensitive_key(key) and isinstance(value, str): values.add(value)
                collect(value)
        elif isinstance(data, list):
            for value in data: collect(value)

    credentials = [ROOT / '.env', LAB / 'env.local', *sorted((ROOT / 'artifacts').rglob('*.local'))]
    for path in credentials:
        if not path.exists(): continue
        text = path.read_text(encoding='utf-8-sig')
        if text.lstrip().startswith(('{', '[')):
            collect(json.loads(text))
        else:
            for line in text.splitlines():
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    if sensitive_key(key): values.add(value.strip("'\""))
    for path in (ROOT / 'artifacts/functional').rglob('*.json'):
        collect(json.loads(path.read_text(encoding='utf-8-sig')))
    return values


def decode(data):
    if data.startswith((b'\xff\xfe', b'\xfe\xff')): return data.decode('utf-16'), 'utf-16'
    return data.decode('utf-8-sig'), 'utf-8'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def archive_record(output, path, label, redactor):
    raw = path.read_bytes(); text, encoding = decode(raw)
    if path.suffix.lower() == '.json':
        text = json.dumps(redactor.structured(json.loads(text)), ensure_ascii=False, indent=2)
    elif path.suffix.lower() == '.jsonl':
        text = '\n'.join(json.dumps(redactor.structured(json.loads(line)), ensure_ascii=False)
                         for line in text.splitlines() if line.strip())
    text = redactor.text(text)
    normalized = '\n'.join(line.rstrip() for line in text.splitlines()) + ('\n' if text else '')
    public = normalized.encode('utf-8')
    destination = output / 'sources' / label
    destination = destination.with_name(destination.stem + '.redacted' + destination.suffix)
    if destination.exists(): raise FileExistsError('Do not overwrite an archived source')
    destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(public)
    if digest(path.read_bytes()) != digest(raw): raise RuntimeError('A source changed while archiving')
    return dict(source=label, source_sha256=digest(raw), source_bytes=len(raw), source_encoding=encoding,
        archived_path=destination.relative_to(output).as_posix(), archived_sha256=digest(public),
        archived_bytes=len(public), source_lines=len(raw.splitlines()), archived_lines=len(public.splitlines()),
        source_modified_utc=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())


def native_linux_sources(private):
    command = ['wsl', '-d', 'CloudDrive-E1-Native', '-u', 'root', '--exec']
    active = subprocess.check_output(command + ['sh', '-c',
        'for p in /sys/fs/cgroup/cloud-drive-e1-native/*/cgroup.procs; do test -f "$p" && cat "$p"; done; true'])
    if active.strip(): raise RuntimeError('Native experiment is active; leave it running and archive after shutdown')
    try:
        paths = subprocess.check_output(command + ['find', '/opt/e1-native/logs', '/opt/e1-native/data/mysql',
            '-maxdepth', '1', '-type', 'f', '(', '-name', '*.log', '-o', '-name', '*.err', ')', '-print']).decode().splitlines()
        sources = []
        for guest in paths:
            relative = guest.removeprefix('/opt/e1-native/')
            if relative == guest or '/' in Path(relative).name or '..' in Path(relative).parts:
                raise ValueError('Unexpected native log path')
            path = private / 'native-linux' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(subprocess.check_output(command + ['cat', guest]))
            stamp = int(subprocess.check_output(command + ['stat', '-c', '%Y', guest]).decode())
            os.utime(path, (stamp, stamp))
            sources.append((path, 'native-wsl/opt/e1-native/' + relative))
        return sources
    finally:
        subprocess.run(['wsl', '--terminate', 'CloudDrive-E1-Native'], capture_output=True, check=True, timeout=30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', required=True)
    parser.add_argument('--native-wsl', action='store_true', help='Also capture file logs in the stopped dedicated native WSL environment')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9-]+', args.name): raise ValueError('Invalid archive name')
    output = ROOT / 'experiments/log-archive' / args.name
    if output.exists(): raise FileExistsError('Use a fresh archive name')
    captured = datetime.now(timezone.utc).isoformat()
    source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    original_index = []
    tree = subprocess.check_output(['git', 'ls-tree', '-rlz', 'HEAD', '--', 'experiments'], cwd=ROOT)
    for entry in tree.split(b'\0'):
        if not entry: continue
        metadata, path = entry.split(b'\t', 1)
        _, kind, oid, size = metadata.split()
        if kind == b'blob':
            original_index.append(dict(path=path.decode('utf-8'), git_blob=oid.decode(), bytes_in_git=int(size)))
    # Public CSV/JSON/execution logs are already versioned; retain their original Git blob identifiers.
    missing = []
    for command in [['git', 'ls-files', '--others', '--exclude-standard', '--', 'experiments'],
                    ['git', 'ls-files', '--others', '--ignored', '--exclude-standard', '--', 'experiments']]:
        missing.extend(subprocess.check_output(command, cwd=ROOT, text=True).splitlines())
    if missing: raise RuntimeError('Existing experiment records are not all tracked: ' + ', '.join(missing))
    sources = [(p, 'artifacts/' + p.relative_to(ROOT / 'artifacts').as_posix())
               for p in sorted((ROOT / 'artifacts').rglob('*')) if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES
               and ROOT / 'artifacts/log-archive' not in p.parents]
    if LAB.exists():
        sources.extend((p, 'native-lab/' + p.relative_to(LAB).as_posix()) for p in sorted(LAB.rglob('*'))
                       if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES)
    redactor = Redactor(secret_values())
    output.mkdir(parents=True)
    records, containers = [], []

    def archive(path, label):
        records.append(archive_record(output, path, label, redactor))

    for path, label in sources: archive(path, label)
    identifiers = subprocess.check_output(['docker', 'ps', '-a', '--filter', 'label=com.docker.compose.project=cloud-drive-course',
        '--format', '{{.ID}}'], cwd=ROOT, text=True).splitlines()
    if len(identifiers) != 6: raise RuntimeError('Expected six original course containers for the retained-log snapshot')
    private = ROOT / 'artifacts/log-archive' / args.name
    private.mkdir(parents=True, exist_ok=False)
    for identifier in identifiers:
        template = '{{json .Config.Labels}}'
        labels = json.loads(subprocess.check_output(['docker', 'inspect', '--format', template, identifier], cwd=ROOT, text=True))
        service = labels['com.docker.compose.service']
        if service not in {'auth-service', 'file-service', 'share-service', 'frontend', 'mysql', 'minio'}:
            raise RuntimeError('Unexpected service in course project')
        result = subprocess.run(['docker', 'logs', '--timestamps', '--until', captured, identifier], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True, timeout=60)
        raw_path = private / (service + '.log'); raw_path.write_bytes(result.stdout)
        archive(raw_path, 'docker-retained/' + service + '.log')
        config = json.loads(subprocess.check_output(['docker', 'inspect', '--format', '{{json .HostConfig.LogConfig}}', identifier], cwd=ROOT, text=True))
        containers.append(dict(service=service, container=identifier, log_config=config, capture_until_utc=captured))
    if args.native_wsl:
        for path, label in native_linux_sources(private): archive(path, label)
    # Verify generic credential forms as well as all known long secret values before publishing.
    for record in records:
        public = (output / record['archived_path']).read_text(encoding='utf-8')
        if re.search(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', public):
            raise RuntimeError('JWT remains in redacted evidence')
        if any(value in public for value in redactor.secrets if len(value) >= 12):
            raise RuntimeError('Known credential remains in redacted evidence')
    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    save('existing-records.json', dict(source_commit=source_commit, files=original_index,
        note='git_blob identifies canonical committed bytes, independent of Windows working-tree line endings'))
    save('manifest.json', dict(captured_utc=captured, source_commit=source_commit, records=records, containers=containers,
        archiver_source_sha256=digest(Path(__file__).read_bytes()), native_wsl_file_logs_captured=args.native_wsl,
        original_experiment_files=len(original_index), archived_sources=len(records),
        normalization='UTF-8/LF; trailing line whitespace removed; JSON credential fields and log credentials redacted',
        original_sources_retained=True, excluded='Credential-only .local/.env files, compiled classes, helper scripts, image exports and VHDX files',
        coverage='All existing tracked experiment records plus retained local text evidence. Docker snapshot includes only logs still retained by the original six containers, up to capture_until_utc; removed containers and previously rotated logs cannot be recovered. Existing E2 stage logs remain in experiments/E2.'))
    print('Archived', len(records), 'retained sources; indexed', len(original_index), 'existing experiment records')


if __name__ == '__main__': main()
