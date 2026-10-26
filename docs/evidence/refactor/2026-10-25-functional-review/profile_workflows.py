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
    profiler=cProfile.Profile()
    start=time.perf_counter()
    result=profiler.runcall(function)
    elapsed=time.perf_counter()-start
    stats=pstats.Stats(profiler)
    calls={}; hot=[]
    for (filename,line,name),(primitive,total,self_s,cumulative_s,callers) in stats.stats.items():
        normalized=filename.replace('\\','/')
        if '/am3d/' not in normalized:continue
        rel='am3d/'+normalized.split('/am3d/',1)[1]
        key=rel+':'+name
        if (rel in ['am3d/core/scene.py','am3d/core/script.py'] and name=='evaluate_scene') or name=='render_frame_image':
            calls[key]=calls.get(key,0)+total
        hot.append({'function':key,'calls':total,'self_seconds':self_s,'cumulative_seconds':cumulative_s})
    return result,{'label':label,'seconds':elapsed,'calls':calls,
        'hotspots':sorted(hot,key=lambda row:row['cumulative_seconds'],reverse=True)[:10]}

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
path=out/'profile.json'
path.write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'source':str(source),'samples':[{'label':r['label'],'calls':r['calls'],'seconds':round(r['seconds'],3)} for r in records]}))
