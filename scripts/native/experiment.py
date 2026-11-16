"""Native E1 P1-P4 controller; request generation/statistics reused unchanged."""
import argparse
from contextlib import redirect_stdout
import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

import psutil

from runtime import Runtime, ROOT, LAB, LINUX, DISTRO, Client, MIB, checksum, save, utc
from sampling import Sampler
sys.path.insert(0, str(ROOT / "scripts/smoke"))
sys.path.insert(0, str(ROOT / "scripts/deployment"))
from functional import Acceptance
from e2_support import sanitize, inventory
from common import prepare, payload
from workload import Workload
from run import wait_stable
from analyze import analyze_round


def smoke(runtime, folder):
    class NativeAcceptance(Acceptance):
        def sql(self, statement): return runtime.sql(statement)
        def compose(self, *args, **kwargs): raise RuntimeError("Docker operations forbidden in native smoke")
    suite = NativeAcceptance(runtime.base, runtime.env_file)
    output = io.StringIO(); fatal = None
    try:
        with redirect_stdout(output):
            suite.accounts(); suite.directories_and_files(); suite.sharing(); suite.deletion()
    except Exception as error:
        fatal = type(error).__name__
    finally:
        suite.cleanup(); suite.http.close()
    save(folder / "smoke.json", dict(utc=utc(), passed=sum(x["status"] == "PASS" for x in suite.results),
        total=len(suite.results), fatal=fatal, results=suite.results))
    secret_values = [v for k,v in runtime.values.items() if any(s in k for s in ["PASSWORD","SECRET","TOKEN"])]
    (folder / "smoke.log").write_text(sanitize(output.getvalue(), [*secret_values,*suite.sensitive]),encoding="utf-8")
    if fatal: raise RuntimeError("Native full API smoke failed")
    print("Native API smoke passed " + str(len(suite.results)) + " checks",flush=True)


def environment(runtime, folder):
    baseline = json.loads((ROOT / "experiments/E1/20261116-e1-formal-ipv4-summary/environment.json").read_text())
    system = runtime.shell("uname -a; cat /etc/os-release; printf 'CPUS='; nproc; head -n 1 /proc/meminfo; cat /sys/fs/cgroup/cloud-drive-e1-native/cgroup.subtree_control").stdout.decode()
    mem = int(re.search(r"MemTotal:\s+(\d+)",system)[1]) * 1024
    cpus = int(re.search(r"CPUS=(\d+)",system)[1])
    if cpus != baseline["docker"]["NCPU"] or abs(mem-baseline["docker"]["MemTotal"]) > MIB:
        raise RuntimeError("Native CPU/memory budget differs from the container baseline")
    programs = {}
    for name, args in [("java",["/opt/java/openjdk/bin/java","-XshowSettings:vm","-version"]),
                       ("minio",[LINUX+"/bin/minio","--version"]),
                       ("mysql",[LINUX+"/mysql-image/lib64/ld-linux-x86-64.so.2","--library-path",LINUX+"/mysql-image/lib64:"+LINUX+"/mysql-image/usr/lib64/mysql/private",LINUX+"/mysql-image/usr/sbin/mysqld","--version"]),
                       ("nginx",[LINUX+"/nginx-image/lib/ld-musl-x86_64.so.1","--library-path",LINUX+"/nginx-image/lib:"+LINUX+"/nginx-image/usr/lib",LINUX+"/nginx-image/usr/sbin/nginx","-v"])]:
        result=runtime.wsl(*args);programs[name]=(result.stdout+result.stderr).decode().strip()
    hashes = runtime.shell("sha256sum " + " ".join([LINUX+"/apps/auth-service/app.jar",LINUX+"/apps/file-service/app/app.jar",LINUX+"/apps/share-service/app.jar",LINUX+"/bin/minio",LINUX+"/nginx-image/usr/sbin/nginx",LINUX+"/mysql-image/usr/sbin/mysqld"])).stdout.decode()
    data = dict(captured_utc=utc(), source_commit=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),
        branch=subprocess.check_output(["git","branch","--show-current"],text=True).strip(),
        mode="six direct Linux processes and matching periodic health probes; no Docker business containers",
        distro=DISTRO, system=system, linux_cpus=cpus, linux_memory_bytes=mem, programs=programs, program_sha256=hashes,
        usable_memory_difference_from_reference_bytes=mem-baseline['docker']['MemTotal'],
        memory_budget_note='Same configured 4 GiB WSL budget; up to 1 MiB usable-MemTotal boot-reservation variation accepted and recorded',
        provenance=json.loads((LAB/"provenance.json").read_text()), request_base_url=runtime.base,
        storage="Native WSL ext4 VHDX on Windows D, container reference VHDX on C; both partitions on physical disk 0",
        cgroup="Dedicated child groups for accounting, no service CPU/memory hard limits",
        cpu_definition="cgroup usage_usec / monotonic wall time; container reference uses Engine system-CPU normalization",
        memory_definition="memory.current minus inactive_file, same working-set convention as reference; RSS/PSS additionally recorded",
        load_tool="Same Windows Python/requests closed-VU generator, 1 s think time", host_os=platform.platform(),
        disk_free_bytes={d:shutil.disk_usage(d).free for d in ["C:/","D:/"]},
        initial_database_records=runtime.sql("SELECT COUNT(*) FROM file_db.sys_file"),
        harness_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*Path(__file__).parent.glob('*.py'),*Path(__file__).parent.glob('*.sh'),Path(__file__).with_name('NativeSampler.java'),ROOT/'scripts/performance/workload.py',ROOT/'scripts/performance/common.py']})
    save(folder/"environment.json",data)
    return data


def round_run(runtime, batch, spec, fixtures, snapshot, pilot):
    folder=ROOT/'experiments/E1'/(batch+f"-{spec['scenario']}-vu{spec['vus']:02}-r{spec['repeat']}")
    folder.mkdir()
    active=fixtures[:spec['vus']]
    if spec['scenario']=='P2' and shutil.disk_usage('D:/').free < len(active)*150*MIB+2*1024**3:
        raise RuntimeError('Insufficient native data-drive headroom')
    runtime.ready()
    before=checksum(runtime.base,active)
    for fixture in active:
        client=Client(runtime.base);client.login(fixture)
        quota=client.data('/quota');client.session.close()
        if quota['totalBytes']-quota['usedBytes']<150*MIB:
            raise RuntimeError('Insufficient native quota for complete upload cap')
    warmup,duration,cooldown=(3,5,3) if pilot else (30,120,30)
    work=dict(**spec,run_id=folder.name,batch=batch,file_size_bytes=MIB,request_base_url=runtime.base,
        warmup_seconds=warmup,measure_seconds=duration,minimum_cooldown_seconds=cooldown,
        max_uploads_per_vu_including_warmup=150,complete=False,upload_cap_hit_by_vu=[False]*len(active))
    save(folder/'workload.json',work);save(folder/'environment.json',snapshot)
    def log(message):
        line=utc()+' '+folder.name+': '+message
        print(line,flush=True)
        with (folder/'execution.log').open('a',encoding='utf-8') as f:f.write(line+'\n')
    sampler=Sampler(runtime,folder);load=None
    try:
        load=Workload(runtime.base,active,folder,folder.name,spec['scenario'])
        work['jwt_remaining_seconds_before_warmup']=load.jwt_remaining
        work['warmup']=load.phase('warmup',warmup,log)
        work['measurement']=load.phase('measure',duration,log)
        work['upload_cap_hit_by_vu']=load.cap_hits;work['upload_requests_by_vu_including_warmup']=load.upload_counts
        load.close();load=None
        save(folder/'checksum.json',dict(before=before,after=checksum(runtime.base,active)))
        maintenance=runtime.cleanup_uploads(active) if spec['scenario']=='P2' else dict(logical_files_deleted=0,quota_restored=True,maintenance_outside_measurement=True)
        save(folder/'cleanup.json',maintenance)
        if spec['scenario']=='P4':
            with (folder/'downstream.csv').open('w',newline='',encoding='utf-8') as file:
                writer=csv.DictWriter(file,fieldnames=['utc','sample_epoch','operation','duration_ms','request_id','status'])
                writer.writeheader()
                for line in (runtime.private/'share-service.log').read_text(encoding='utf-8',errors='replace').splitlines():
                    try:
                        stamp=line.split()[0];epoch=datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp()
                    except (ValueError,IndexError):continue
                    if not work['measurement']['start_epoch']<=epoch<work['measurement']['end_epoch']:continue
                    match=re.search(r'dependency operation=(metadata|content) requestId=([A-Za-z0-9_-]+) durationMs=(\d+)',line)
                    if match:writer.writerow(dict(utc=stamp,sample_epoch=epoch,operation=match[1],request_id=match[2],duration_ms=match[3],status=''))
                    match=re.search(r'request id=([A-Za-z0-9_-]+) category=anonymous-share status=(\d+) durationMs=(\d+)',line)
                    if match:writer.writerow(dict(utc=stamp,sample_epoch=epoch,operation='share_request',request_id=match[1],status=match[2],duration_ms=match[3]))
        work['cooldown']=wait_stable(folder,cooldown,log)
        work['complete']=True
        log('round complete')
    finally:
        if load:load.close()
        save(folder/'workload.json',work);sampler.close()
    return folder.name


def restore_original(folder):
    try:subprocess.run(['docker','desktop','start'],capture_output=True,timeout=60)
    except subprocess.TimeoutExpired:pass
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        try:result=subprocess.run(['docker','info','--format','{{.OSType}}'],capture_output=True,timeout=15)
        except subprocess.TimeoutExpired:
            time.sleep(3);continue
        if result.returncode==0:break
        time.sleep(3)
    else:raise RuntimeError('Docker Desktop did not become ready for original-service restoration')
    subprocess.run(['docker','compose','start'],cwd=ROOT,capture_output=True,check=True,timeout=180)
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        rows=inventory('cloud-drive-course')
        if len(rows)==6 and all(x['status']=='running' and x['health']=='healthy' for x in rows):break
        time.sleep(2)
    else:raise RuntimeError('Original E1 containers did not become healthy')
    before=json.loads((LAB/'e1-before.json').read_text())
    if {(x['service'],x['id'],x['image_id']) for x in rows}!={(x['service'],x['id'],x['image_id']) for x in before}:
        raise RuntimeError('Original E1 container identity changed')
    original=json.loads((ROOT/'artifacts/e1/20261116-e1-formal/fixtures.local').read_text())
    save(folder/'original-state-restored.json',dict(utc=utc(),containers=rows,
        one_mib_checks=checksum('http://127.0.0.1:8080',original),
        twenty_mib_checks=checksum('http://127.0.0.1:8080',original[:5],True)))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--batch',required=True);parser.add_argument('--pilot',action='store_true')
    args=parser.parse_args()
    if not re.fullmatch(r'[a-z0-9_-]+',args.batch):raise ValueError('Invalid batch')
    folder=ROOT/'experiments/E1'/(args.batch+'-summary');folder.mkdir(exist_ok=False)
    private=ROOT/'artifacts/native'/args.batch;private.mkdir(parents=True,exist_ok=False)
    runtime=Runtime(private);manifest=dict(batch=args.batch,pilot=args.pilot,mode='native',started_utc=utc(),completed=[])
    save(folder/'matrix.json',manifest)
    try:
        runtime.install();runtime.start();smoke(runtime,folder)
        snapshot=environment(runtime,folder)
        credentials=private/'fixtures.local'
        fixtures=prepare(runtime.base,credentials,users=5 if args.pilot else 20)
        snapshot['dataset']=dict(vus=len(fixtures),list_entries_per_vu=100,one_mib_seed_files=len(fixtures),
            unused_twenty_mib_seed_files=min(5,len(fixtures)),total_file_records_after_setup=int(runtime.sql('SELECT COUNT(*) FROM file_db.sys_file')))
        save(folder/'environment.json',snapshot)
        sampler_folder=folder/'idle';sampler_folder.mkdir()
        s=Sampler(runtime,sampler_folder);time.sleep(5 if args.pilot else 30);s.close()
        matrix=[]
        if args.pilot:matrix=[dict(scenario=x,vus=2,repeat=0,order=i+1) for i,x in enumerate(['P1','P2','P3','P4'])]
        else:
            for scenario in ['P1','P2','P3','P4']:
                for repeat,order in enumerate([[5,10,20],[10,20,5],[20,5,10]],1):
                    for vus in order:matrix.append(dict(scenario=scenario,vus=vus,repeat=repeat,order=len(matrix)+1))
        manifest.update(source_commit=snapshot['source_commit'],matrix=matrix)
        save(folder/'matrix.json',manifest)
        for i,spec in enumerate(matrix,1):
            print(f"MATRIX {i}/{len(matrix)} {spec['scenario']} VU={spec['vus']} repeat={spec['repeat']}",flush=True)
            manifest['completed'].append(round_run(runtime,args.batch,spec,fixtures,snapshot,args.pilot))
            save(folder/'matrix.json',manifest)
        manifest['complete']=True
        if args.pilot:save(folder/'pilot-data-cleanup.json',runtime.cleanup_fixtures(fixtures))
    except Exception as error:
        manifest['complete']=False;manifest['fatal_type']=type(error).__name__
        raise
    finally:
        runtime.stop();manifest['finished_utc']=utc();save(folder/'matrix.json',manifest)
        if not args.pilot:
            restore_original(folder);manifest['original_services_restored']=True;save(folder/'matrix.json',manifest)
    print('NATIVE MATRIX COMPLETE '+args.batch,flush=True)


if __name__=='__main__':
    raise SystemExit(main())
