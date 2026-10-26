"""Bounded offline workflow profiles, usable with original or refactored source."""
import argparse
import copy
import cProfile
import json
from pathlib import Path
import pstats
import statistics
import sys
import time

parser=argparse.ArgumentParser()
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--repeats',type=int,choices=(1,2,3),default=3)
args=parser.parse_args()
source=args.source.resolve(); out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
sys.path.insert(0,str(source))
from am3d.core.script import Session
from am3d.recipes.executor import RecipeExecutor
from am3d.ai.checks import check_artifacts

def run_profile(label, function):
    start=time.perf_counter()
    result=function()
    return result,{'label':label,'seconds':time.perf_counter()-start,'calls':{},'hotspots':[]}

records=[];checks=[]
for repeat in range(args.repeats):
    case=out/f'exports-{repeat}';case.mkdir()
    recipe={'version':1,'name':'profile multi-format','objects':[
        {'name':'body','primitive':'box','params':{'width':1.,'height':1.,'depth':.8}},
        {'name':'lid','primitive':'sphere','params':{'radius':.3,'sections':8,'rings':4}}],
        'materials':[], 'exports':[{'format':'obj','path':'mesh.obj'},
            {'format':'glb','path':'mesh.glb'},
            {'format':'toon_sheet','path':'views','params':{'views':2,'size':64}}]}
    result,record=run_profile('multi_format_export',lambda:RecipeExecutor(
        Session(),output_root=str(case),safe_artifact_names=True).execute(recipe))
    assert result.ok,result.errors
    records.append(record)

for repeat in range(args.repeats):
    case=out/f'animation-{repeat}';case.mkdir()
    recipe={'name':'three component motion','objects':[
        {'name':'driver','primitive':'box','params':{'width':1.,'height':1.,'depth':.8},
         'bones':[{'name':'root','head':[0,0,0],'tail':[0,.5,0]}]},
        {'name':'target','primitive':'box','params':{'width':1.,'height':1.,'depth':.8,'skeleton':'driver'}},
        {'name':'third','primitive':'box','params':{'width':1.,'height':1.,'depth':.8,'skeleton':'driver'}}],
        'materials':[], 'actions':[{'name':'turn','kind':'custom','duration':1.,'character':'driver',
            'channels':[{'bone':'root','property':'rotate','keys':[
                {'time':0,'value':[0,0,0]},{'time':.5,'value':[0,0,60]},{'time':1,'value':[0,0,0]}]}]}],
        'exports':[]}
    session=Session(); result=RecipeExecutor(session,output_root=str(case),safe_artifact_names=True).execute(recipe)
    assert result.ok,result.errors
    session.save_project(str(case/'project.am3d'))
    requirements={'rig':{'required':True,'action_kind':'custom','expected_bones':['root'],
        'bound_components':['driver','target','third'],'must_deform_components':['driver','target','third']}}
    brief={'brief':'Three boxes rotating with one shared rig.'}
    report,record=run_profile('three_component_animation_check',lambda:check_artifacts(
        recipe,case,brief=brief,generation={'run_id':'22222222-2222-4222-8222-222222222222'},requirements=requirements))
    assert report['ok'],report
    checks.append(report)
    records.append(record)

summary={'source':str(source),'qualification':'offline diagnostic profile, not a speed benchmark',
    'samples':records,'warm_medians_seconds':{},'animation_reports':checks}
for label in {item['label'] for item in records}:
    times=[item['seconds'] for item in records if item['label']==label]
    summary['warm_medians_seconds'][label]=statistics.median(times[1:]) if len(times)>1 else None
import ctypes
from ctypes import wintypes
class Counters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ("peak_ws", "ws", "qpp", "qp", "qnpp", "qnp", "page", "peak_page")]
count = Counters(); count.cb = ctypes.sizeof(count)
kernel=ctypes.WinDLL("kernel32"); kernel.GetCurrentProcess.restype=wintypes.HANDLE
psapi=ctypes.WinDLL("psapi")
psapi.GetProcessMemoryInfo.argtypes=(wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
assert psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(count), count.cb)
summary["peak_working_set_bytes"] = int(count.peak_ws)
summary["qualification"] = "Sequential separate processes; first sample cold, remaining two warm; process peak working set includes imports and both fixtures. Local software diagnostics only."
path=out/'profile.json'
path.write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'source':str(source),'samples':[{'label':r['label'],'calls':r['calls'],'seconds':round(r['seconds'],3)} for r in records]}))
