"""Capture redacted deployment settings after a completed native matrix."""
import argparse
import hashlib
import io
import json
import platform
import re
import shutil
import subprocess
import sys
import tarfile

import numpy
import matplotlib
import psutil
import requests

from runtime import ROOT, LAB, LINUX, SERVICES, Runtime, save, utc


def main():
    parser=argparse.ArgumentParser();parser.add_argument('batch');args=parser.parse_args()
    if not re.fullmatch(r'[a-z0-9_-]+',args.batch):raise ValueError('Invalid batch')
    folder=ROOT/'experiments/E1'/(args.batch+'-summary')
    matrix=json.loads((folder/'matrix.json').read_text())
    if not matrix.get('complete') or not matrix.get('original_services_restored'):
        raise RuntimeError('Wait for the full matrix and original-service restoration')
    values=dict(line.split('=',1) for line in (LAB/'env.local').read_text().splitlines() if '=' in line and not line.startswith('#'))
    redacted={key:('[REDACTED]' if any(word in key for word in ['PASSWORD','SECRET','TOKEN','ACCESS_KEY','MINIO_ROOT_USER']) else value)
        for key,value in values.items()}
    runtime=Runtime(ROOT/'artifacts/native'/args.batch)
    configs={name:runtime.wsl('cat',LINUX+'/nginx/'+name).stdout.decode() for name in ['nginx.conf','default.conf','course-proxy.conf']}
    service_pids={service:runtime.shell('cat /sys/fs/cgroup/cloud-drive-e1-native/'+service+'/cgroup.procs 2>/dev/null || true').stdout.decode().split()
        for service in SERVICES}
    if any(service_pids.values()):raise RuntimeError('Native service cgroup still has processes after matrix shutdown')
    paths={
        'auth-service':('/app/app.jar',LINUX+'/apps/auth-service/app.jar'),
        'file-service':('/app/app.jar',LINUX+'/apps/file-service/app/app.jar'),
        'share-service':('/app/app.jar',LINUX+'/apps/share-service/app.jar'),
        'mysql':('/usr/sbin/mysqld',LINUX+'/mysql-image/usr/sbin/mysqld'),
        'minio':('/usr/bin/minio',LINUX+'/bin/minio'),
        'frontend':('/usr/sbin/nginx',LINUX+'/nginx-image/usr/sbin/nginx')}
    binaries={}
    for service,(container_path,native_path) in paths.items():
        identifier=subprocess.check_output(['docker','compose','ps','-q',service],cwd=ROOT,text=True).strip()
        copied=subprocess.run(['docker','cp','-L',identifier+':'+container_path,'-'],
            cwd=ROOT,capture_output=True,check=True,timeout=60).stdout
        with tarfile.open(fileobj=io.BytesIO(copied),mode='r:') as archive:
            files=[member for member in archive.getmembers() if member.isfile()]
            if len(files)!=1:raise RuntimeError('Expected one reference binary in Docker copy stream')
            with archive.extractfile(files[0]) as binary:container=hashlib.file_digest(binary,'sha256').hexdigest()
        del copied
        native=runtime.wsl('sha256sum',native_path).stdout.decode().split()[0]
        binaries[service]=dict(container_sha256=container,native_sha256=native,match=container==native)
    command='find . -type f -exec sha256sum {} + | LC_ALL=C sort'
    native=runtime.shell('cd '+LINUX+'/nginx-image/usr/share/nginx/html && '+command).stdout.decode().splitlines()
    container=subprocess.run(['docker','compose','exec','-T','frontend','sh','-c',
        'cd /usr/share/nginx/html && '+command],cwd=ROOT,capture_output=True,check=True,timeout=30).stdout.decode().splitlines()
    if not all(item['match'] for item in binaries.values()) or native!=container:
        raise RuntimeError('Native/reference binary or frontend content mismatch')
    save(folder/'binary-equivalence.json',dict(captured_utc=utc(),services=binaries,
        frontend_files=len(native),frontend_files_all_match=True,frontend_sha256_lines=native))
    save(folder/'configuration.redacted.json',dict(captured_utc=utc(),environment=redacted,nginx=configs,
        service_launcher='scripts/native/service.sh at '+matrix['source_commit'],
        database_bootstrap='scripts/native/runtime.py at '+matrix['source_commit'],
        note='Secrets replaced by key; private values remain outside the repository'))
    save(folder/'post-run.json',dict(captured_utc=utc(),python=sys.version,requests=requests.__version__,
        numpy=numpy.__version__,matplotlib=matplotlib.__version__,psutil=psutil.__version__,windows=platform.platform(),
        native_service_cgroup_pids=service_pids,native_services_stopped=True,
        disk_free_bytes={drive:shutil.disk_usage(drive).free for drive in ['C:/','D:/']}))
    print('Captured redacted settings; all six native service cgroups are empty')


if __name__=='__main__':main()
