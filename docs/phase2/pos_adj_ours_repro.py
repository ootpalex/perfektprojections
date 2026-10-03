"""
pos_adj_ours_repro.py - re-derives the dashboard's FROZEN positional adjustments from its own
career history by calling its research code directly (read-only; needs pandas, so run it with
the fork venv). It is evidence for docs/phase2/pos_adj.md section 3, not part of the engine.

    <venv python> docs/phase2/pos_adj_ours_repro.py /tmp/out.json

Method exactly as the dashboard froze it: switcher on ZR at H_def 5 / cut_def 20, offence at
H_off 2.5 / cut_off 8, blend 1/2 + 1/2, C and DH from offence, DH = min of nine, then the eight
field positions shifted to mean 0. Units: runs per 162 games (1458 IP).
Reads: $OOTP_ANALYSIS/calibration/historical_pos_adj.py and ../data/*_career_*_stats.csv.
"""
import sys, json, time
import os
sys.path.insert(0, os.path.join(os.environ.get('OOTP_ANALYSIS','/Users/alex/Projects/ootp/analysis/positional-adjustments'),'calibration'))
import historical_pos_adj as hp, numpy as np
def run(prefix,lid,year_min,hd=5,cd=20,ho=2.5,co=8):
    b,f=hp.load(csv_prefix=prefix,lid=lid,year_min=year_min)
    consts=hp.season_constants(b); off_df=hp.player_off(b,consts)
    fp=f[f.position.isin(hp.FIELD_POS)]
    fbp={}
    for (pid,yr),g in fp.groupby(['player_id','year']): fbp[(pid,yr)]=dict(zip(g.position,g.inn))
    pps=set(map(tuple,f[f.position==1][['player_id','year']].values))
    obs,_=hp.build_defensive_obs(f)
    years=sorted(set(int(y) for y in f.year.unique() if y>=year_min)); end=years[-1]
    sub=obs[(obs.year<=end)&(obs.year>=end-cd+1)]
    d=hp.solve_defensive(sub,end=end,halflife=hd)
    yrs=[y for y in years if end-co+1<=y<=end]
    o=hp.offensive_window(off_df,fbp,pps,yrs,end=end,halflife=ho)
    bl=hp.blend(d,o)
    lo=min(bl.values()); bl['DH']=min(bl['DH'],lo)
    f8=sum(bl[k] for k in ['C','1B','2B','3B','SS','LF','CF','RF'])/8
    fin={k:v-f8 for k,v in bl.items()}
    return dict(end=end,nobs=len(sub),defn=d,off=o,blend=bl,final=fin,obs=obs,off_df=off_df,fbp=fbp,pps=pps,b=b,f=f)
if __name__=='__main__':
    out={}
    for name,(p,l,y) in {'BLM':('players_career',144,2016),'SSB':('ssb_career',None,2021)}.items():
        t=time.time(); r=run(p,l,y)
        print(name,'end',r['end'],'nobs',r['nobs'],round(time.time()-t))
        print(' def',{k:round(v,2) for k,v in r['defn'].items()})
        print(' off',{k:round(v,2) for k,v in r['off'].items()})
        print(' final',{k:round(v,2) for k,v in r['final'].items()})
        out[name]={k:r[k] for k in ('end','nobs','defn','off','blend','final')}
    json.dump(out,open(sys.argv[1],'w'),indent=1)
