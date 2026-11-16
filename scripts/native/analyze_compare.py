"""Recompute native metrics and compare disjoint, three-repeat E1 conditions."""
import argparse
import json
import statistics
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/performance'))
from analyze import analyze_round,aggregate,read_csv,write_csv
from common import save


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--native',required=True)
    parser.add_argument('--reference',default='20261116-e1-combined')
    args=parser.parse_args()
    base=ROOT/'experiments/E1';folder=base/(args.native+'-summary')
    manifest=json.loads((folder/'matrix.json').read_text())
    if not manifest.get('complete') or len(manifest['completed'])!=36:
        raise RuntimeError('Require all 36 native base rounds; keep incomplete batches separate')
    native=[analyze_round(base/name) for name in manifest['completed']]
    reference=[x for x in json.loads((base/(args.reference+'-summary')/'metrics.json').read_text()) if x['scenario'] in ['P1','P2','P3','P4']]
    if len(reference)!=36:raise RuntimeError('Reference requires 36 base rounds')
    expected={(s,v,r) for s in ['P1','P2','P3','P4'] for v in [5,10,20] for r in [1,2,3]}
    for rows in [native,reference]:
        if {(r['scenario'],r['vus'],r['repeat']) for r in rows}!=expected:
            raise RuntimeError('Require the complete 4 x 3 x 3 design with unique repeats')
        if not all(r['complete'] and r['file_size_bytes']==1048576 and r['measure_seconds']==120 for r in rows):
            raise RuntimeError('Incomplete round or mismatched base protocol')
    save(folder/'metrics.json',native);write_csv(folder/'aggregate.csv',aggregate(native))
    write_csv(folder/'per-round.csv',[dict(run_id=r['run_id'],scenario=r['scenario'],vus=r['vus'],repeat=r['repeat'],file_size_bytes=r['file_size_bytes'],
        requests=r['requests'],failures=r['failures'],success_rate=r['success_rate'],http_rps=r['rps'],
        iteration_rps=r['iterations']['rps'],mean_ms=r['latency_ms']['mean'],p50_ms=r['latency_ms']['p50'],
        p95_ms=r['latency_ms']['p95'],p99_ms=r['latency_ms']['p99'],mib_per_second=r['bytes_per_second']/2**20,
        file_cpu_peak=r['resources']['file-service']['cpu_peak'],
        file_memory_peak_mib=r['resources']['file-service']['memory_peak_bytes']/2**20) for r in native])
    write_csv(folder/'resource-summary.csv',[dict(run_id=r['run_id'],scenario=r['scenario'],vus=r['vus'],
        repeat=r['repeat'],service=service,**values) for r in native for service,values in r['resources'].items()])
    checksum_checks=[];cleanups=[];quality=[]
    for result in native:
        run=base/result['run_id']
        checks=json.loads((run/'checksum.json').read_text())
        checksum_checks.extend(checks['before']+checks['after'])
        cleanups.append(json.loads((run/'cleanup.json').read_text()))
        work=json.loads((run/'workload.json').read_text())
        collector=json.loads((run/'collector.json').read_text())
        host=[r for r in read_csv(run/'load-generator.csv') if work['measurement']['start_epoch']<=float(r['sample_epoch'])<work['measurement']['end_epoch']]
        quality.append(dict(run_id=result['run_id'],cooldown_stable=work['cooldown']['stable'],upload_cap_hit=result['cap_hit'],
            collector_errors=collector['errors'],host_samples=len(host),
            plugged_samples=sum(r.get('power_plugged')=='True' for r in host),
            unplugged_samples=sum(r.get('power_plugged')=='False' for r in host),
            collector_cpu_mean_percent=statistics.mean(float(r['collector_cpu_percent']) for r in host),
            collector_rss_mean_mib=statistics.mean(float(r['collector_rss_bytes'])/2**20 for r in host),
            host_cpu_mean_percent=statistics.mean(float(r['host_cpu_percent']) for r in host)))
    if len(checksum_checks)!=840 or not all(c['match'] and c['bytes']==1048576 for c in checksum_checks):
        raise RuntimeError('Native round checksums require 840 matching 1 MiB checks')
    if not all(c['quota_restored'] and c.get('remaining_objects',0)==0 and c.get('pending_cleanup',0)==0 for c in cleanups):
        raise RuntimeError('Native upload cleanup verification failed')
    save(folder/'quality.json',dict(checksum_checks=len(checksum_checks),checksum_all_match=True,
        uploaded_objects_cleaned=sum(c['logical_files_deleted'] for c in cleanups),upload_cleanup_verified=True,rounds=quality))
    pairs=[];resource=[]
    for scenario,vus in sorted({(r['scenario'],r['vus']) for r in native}):
        conditions={name:[r for r in rows if r['scenario']==scenario and r['vus']==vus] for name,rows in [('container',reference),('native',native)]}
        if any(len(rows)!=3 for rows in conditions.values()):raise RuntimeError('Each condition needs three repeats')
        record=dict(scenario=scenario,vus=vus,file_size_bytes=1048576)
        for name,rows in conditions.items():
            record[name+'_requests']=sum(r['requests'] for r in rows)
            record[name+'_failures']=sum(r['failures'] for r in rows)
            record[name+'_timeouts']=sum(r['timeouts'] for r in rows)
            samples=dict(http_rps=[r['rps'] for r in rows],iteration_rps=[r['iterations']['rps'] for r in rows],
                p95_ms=[r['latency_ms']['p95'] for r in rows],p99_ms=[r['latency_ms']['p99'] for r in rows],
                mib_per_second=[r['bytes_per_second']/2**20 for r in rows],
                services_memory_mean_mib=[sum(v['memory_mean_bytes'] for v in r['resources'].values())/2**20 for r in rows])
            for metric,values in samples.items():
                record[name+'_'+metric+'_median']=statistics.median(values)
                record[name+'_'+metric+'_min']=min(values);record[name+'_'+metric+'_max']=max(values)
            for service in rows[0]['resources']:
                resource.append(dict(scenario=scenario,vus=vus,mode=name,service=service,
                    cpu_mean_percent_median=statistics.median(r['resources'][service]['cpu_mean'] for r in rows),
                    memory_mean_mib_median=statistics.median(r['resources'][service]['memory_mean_bytes']/2**20 for r in rows),
                    memory_peak_mib_median=statistics.median(r['resources'][service]['memory_peak_bytes']/2**20 for r in rows)))
        for metric in ['iteration_rps','p95_ms','services_memory_mean_mib']:
            record[metric+'_native_change_percent']=(record['native_'+metric+'_median']/record['container_'+metric+'_median']-1)*100
        pairs.append(record)
    write_csv(folder/'comparison.csv',pairs);write_csv(folder/'comparison-resources.csv',resource)
    save(folder/'comparison.json',dict(reference=args.reference,native=args.native,conditions=pairs,
        native_requests=sum(r['requests'] for r in native),native_failures=sum(r['failures'] for r in native),
        native_timeouts=sum(r['timeouts'] for r in native),
        resource_samples=dict(expected=sum(v['expected_samples'] for r in native for v in r['resources'].values()),
                             actual=sum(v['samples'] for r in native for v in r['resources'].values()),
                             missing_estimate=sum(v['missing_sample_estimate'] for r in native for v in r['resources'].values())),
        interpretation='Observed deployment comparison; same binaries and configured VM budget, different VHDX locations/network paths and separate execution times'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    figures=folder/'figures';figures.mkdir(exist_ok=True)
    names={'P1':'List (100 entries)','P2':'Upload (1 MiB)','P3':'Download (1 MiB)','P4':'Protected share (two HTTP requests/iteration)'}
    for metric,ylabel,filename in [('p95_ms','Per-run HTTP P95 (ms)','deployment-p95'),('iteration_rps','Successful business iterations/s','deployment-throughput')]:
        fig,axes=plt.subplots(2,2,figsize=(11,8),layout='constrained')
        for ax,(scenario,title) in zip(axes.flat,names.items()):
            rows=[r for r in pairs if r['scenario']==scenario]
            for mode,label in [('container','Compose reference'),('native','Direct Linux processes')]:
                prefix=mode+'_'+metric
                center=[r[prefix+'_median'] for r in rows]
                error=[[r[prefix+'_median']-r[prefix+'_min'] for r in rows],[r[prefix+'_max']-r[prefix+'_median'] for r in rows]]
                ax.errorbar([r['vus'] for r in rows],center,yerr=error,marker='o',capsize=4,label=label)
            ax.set(title=title,xlabel='Concurrent VUs; 1 s think time',ylabel=ylabel,xticks=[5,10,20],ylim=(0,None))
            ax.grid(alpha=.2);ax.legend(fontsize=8)
        fig.suptitle('Same application binaries; median and min-max of three repeats')
        for extension in ['png','svg']:fig.savefig(figures/(filename+'.'+extension),dpi=150)
        plt.close(fig)
    import numpy as np
    services=sorted(native[0]['resources'])
    conditions=sorted({(r['scenario'],r['vus']) for r in native})
    matrices={mode:np.array([[statistics.median(r['resources'][service]['memory_peak_bytes']/2**20
        for r in rows if (r['scenario'],r['vus'])==condition) for service in services] for condition in conditions])
        for mode,rows in [('container',reference),('native',native)]}
    fig,axes=plt.subplots(1,2,figsize=(14,7),layout='constrained',sharey=True)
    maximum=max(float(m.max()) for m in matrices.values())
    for ax,(mode,title) in zip(axes,[('container','Compose reference'),('native','Direct Linux processes')]):
        matrix=matrices[mode];heat=ax.imshow(matrix,cmap='YlGnBu',aspect='auto',vmin=0,vmax=maximum)
        ax.set(xticks=range(len(services)),xticklabels=services,yticks=range(len(conditions)),
            yticklabels=[f'{s}, {v} VU' for s,v in conditions],title=title)
        plt.setp(ax.get_xticklabels(),rotation=25,ha='right')
        for i,row in enumerate(matrix):
            for j,value in enumerate(row):ax.text(j,i,f'{value:.0f}',ha='center',va='center',fontsize=8,color='white' if value>maximum*.6 else 'black')
    fig.suptitle('Working-set peaks by service: median of three per-run peaks')
    fig.colorbar(heat,ax=axes,label='MiB; usage minus inactive_file')
    for extension in ['png','svg']:fig.savefig(figures/('deployment-memory-peaks.'+extension),dpi=150)
    plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(13,7),layout='constrained',sharex=True)
    for column,(mode,rows) in enumerate([('Compose reference',reference),('Direct Linux processes',native)]):
        candidates=sorted([r for r in rows if r['scenario']=='P4' and r['vus']==20],key=lambda r:r['latency_ms']['p95'])
        chosen=candidates[1];run=base/chosen['run_id'];work=json.loads((run/'workload.json').read_text())
        start,end=work['measurement']['start_epoch'],work['measurement']['end_epoch']
        samples=[r for r in read_csv(run/'resources.csv') if start<=float(r['sample_epoch'])<end]
        for service in services:
            values=[r for r in samples if r['service']==service and r['cpu_percent']]
            seconds=[float(r['sample_epoch'])-start for r in values]
            axes[0,column].plot(seconds,[float(r['cpu_percent']) for r in values],label=service,linewidth=1)
            axes[1,column].plot(seconds,[float(r['memory_working_set_bytes'])/2**20 for r in values],label=service,linewidth=1)
        axes[0,column].set(title=mode,ylabel='CPU %; 100% = one core')
        axes[0,column].legend(fontsize=8,ncol=2)
        axes[1,column].set(ylabel='Working-set memory (MiB)',xlabel='Seconds from formal-window start')
    for row in axes:
        upper=max(ax.get_ylim()[1] for ax in row)
        for ax in row:ax.set_ylim(0,upper);ax.grid(alpha=.2)
    fig.suptitle('P4, 20 VU: each mode uses its middle run by HTTP P95; CPU estimators differ')
    for extension in ['png','svg']:fig.savefig(figures/('deployment-share-resources.'+extension),dpi=150)
    plt.close(fig)
    for path in figures.glob('*.svg'):
        path.write_text('\n'.join(x.rstrip() for x in path.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8')
    print('Compared 36 native rounds with 36 reference rounds; native requests',sum(r['requests'] for r in native),'failures',sum(r['failures'] for r in native))


if __name__=='__main__':main()
