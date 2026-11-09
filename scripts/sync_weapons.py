#!/usr/bin/env python3
"""Daily BF6 weapon sync. Modelled stats only: upstream changes are not proof of EA balance changes."""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE = "https://raw.githubusercontent.com/raymdl/BF6-Weapon-Analyzer/main/data/"
KEYS = ("rpm","mag","tacRld","emptyRld","bulletVel","recoilV","recoilDir","recoilVar","recoilIncAds","fireMode","availableFireModes","fireModes","dmg","recoil","spread","spreadDyn","reloadSpeed","cal")
RANGES = (0,5,10,15,20,30,40,50,75,100)

def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

def write(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def hashof(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()

def download(file):
    req=urllib.request.Request(SOURCE+file,headers={"User-Agent":"SkyGuy-Weapon-Lab-AutoSync/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=25) as resp:
        body=resp.read(6000000)
        if resp.status!=200 or len(body)>=6000000: raise ValueError("Unexpected source response")
        return json.loads(body)

def validate(weapons, zones, old):
    minimum=max(40,int(len(old or [])*.8))
    if not isinstance(weapons,list) or len(weapons)<minimum: raise ValueError("Roster too small; refusing to update")
    seen=set()
    for w in weapons:
        if not isinstance(w,dict) or not w.get("id") or not w.get("name") or not w.get("cls"): raise ValueError("Invalid weapon record")
        if w["id"] in seen: raise ValueError("Duplicate weapon ID "+w["id"])
        seen.add(w["id"])
        rpm=w.get("rpm")
        if not isinstance(rpm,(int,float)) or not math.isfinite(rpm) or not 0<rpm<=4000: raise ValueError("Invalid RPM")
        curve=w.get("dmg")
        if not isinstance(curve,list) or not curve: raise ValueError("Missing damage curve")
        previous=-1
        for point in curve:
            r,d=point.get("r"),point.get("d")
            if not isinstance(r,(int,float)) or not isinstance(d,(int,float)) or not math.isfinite(r) or not math.isfinite(d) or r<previous or r<0 or d<=0: raise ValueError("Bad damage curve")
            previous=r
    if not isinstance(zones,dict) or not isinstance(zones.get("weapons"),dict) or len(zones["weapons"])<len(weapons)*.7: raise ValueError("Incomplete hitzone data")

def flat(obj, prefix=""):
    if isinstance(obj,dict):
        result={}
        for key,v in obj.items(): result.update(flat(v,(prefix+"." if prefix else "")+key))
        return result
    if isinstance(obj,list):
        result={prefix+".length":len(obj)}
        for i,v in enumerate(obj): result.update(flat(v,prefix+"["+str(i)+"]"))
        return result
    return {prefix:obj}

def neq(a,b):
    if isinstance(a,(int,float)) and isinstance(b,(int,float)) and not isinstance(a,bool) and not isinstance(b,bool):
        return not math.isclose(a,b,abs_tol=0.000001,rel_tol=0)
    return a!=b

def fields(old,new):
    x=flat({k:old.get(k) for k in KEYS})
    y=flat({k:new.get(k) for k in KEYS})
    return [{"field":k,"before":x.get(k),"after":y.get(k)} for k in sorted(set(x)|set(y)) if neq(x.get(k),y.get(k))]

def damage_at(w,r):
    curve=w.get("dmg") or []
    if not curve:return None
    if r<=curve[0]["r"]:return curve[0]["d"]
    for i in range(1,len(curve)):
        a,b=curve[i-1],curve[i]
        if r<=b["r"]:
            if a["r"]==b["r"]:return a["d"]
            return a["d"]+(b["d"]-a["d"])*(r-a["r"])/(b["r"]-a["r"])
    return curve[-1]["d"]

def shot_interval(w,n):
    cycle=w.get("fireMode") in ("burst","pump")
    rounds=int(w.get("burstRounds") or 0) if cycle else 0
    bursts=float(w.get("burstBurstsPerMinute") or 0) if cycle else 0
    if cycle and (w.get("fireMode")=="burst" or w.get("burstRounds") is not None or w.get("burstBurstsPerMinute") is not None):
        if rounds<1 or bursts<=0:return None
    rpm=w.get("burstRpm",w.get("rpm")) if cycle else w.get("rpm")
    if not isinstance(rpm,(float,int)) or rpm<=0:return None
    interval=60000/rpm
    if rounds<=1 or bursts<=0:return interval
    if (n-1)%rounds<rounds-1:return interval
    return max(interval,60000/bursts-(rounds-1)*interval)

def performance(w,range_m=0):
    dmg=damage_at(w,range_m)
    if not dmg or dmg<=0:return {"damage":None,"btk":None,"ttkMs":None}
    btk=math.ceil((100-1e-9)/dmg)
    if btk>1000:return {"damage":round(dmg,5),"btk":btk,"ttkMs":None}
    total=0
    for i in range(1,btk):
        ms=shot_interval(w,i)
        if ms is None:return {"damage":round(dmg,5),"btk":btk,"ttkMs":None}
        total+=ms
    return {"damage":round(dmg,5),"btk":btk,"ttkMs":round(total,4)}

def tournament(w):
    cls=str(w.get("cls","")).lower()
    name=str(w.get("name","")).lower()
    if "shotgun" in cls or "shotgun" in name or "dmr" in cls or "marksman" in cls or ("sniper" in cls and "interdictor" not in name):
        return {"allowed":False,"reason":"Category ban"}
    ttk=performance(w,0)["ttkMs"]
    if ttk is None:return {"allowed":False,"reason":"Unverified TTK"}
    whole=math.floor(ttk+.5)
    return {"allowed":whole>201,"ttk0mDisplayed":whole,"reason":"201 ms or faster banned"}

def main():
    now=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
    weapon_path=DATA/"weapons.json"
    zones_path=DATA/"hit_zones.json"
    old=read(weapon_path,[])
    old_zones=read(zones_path,{"weapons":{}})
    current=download("weapons.json")
    new_zones=download("hit_zones.json")
    validate(current,new_zones,old)
    old_by={w["id"]:w for w in old}
    new_by={w["id"]:w for w in current}
    new_ids=sorted(new_by.keys()-old_by.keys())
    removed_ids=sorted(old_by.keys()-new_by.keys())
    changes=[]
    for wid in sorted(new_by.keys()&old_by.keys()):
        a,b=old_by[wid],new_by[wid]
        changed=fields(a,b)
        for key in ("headshot","limb"):
            before=old_zones.get("weapons",{}).get(wid,{}).get(key)
            after=new_zones["weapons"].get(wid,{}).get(key)
            if neq(before,after): changed.append({"field":"hitZones."+key,"before":before,"after":after})
        if not changed:continue
        distances=sorted({*RANGES,*(p["r"] for p in a["dmg"] if 0<=p["r"]<=100),*(p["r"] for p in b["dmg"] if 0<=p["r"]<=100)})
        ttk_changes=[]
        for d in distances:
            x,y=performance(a,d),performance(b,d)
            if x!=y:ttk_changes.append({"meters":d,"before":x,"after":y})
        ea,eb=tournament(a),tournament(b)
        changes.append({"id":wid,"weapon":b["name"],"type":b["cls"],"fields":changed,"ttkChanges":ttk_changes,
                        "tournamentBefore":ea,"tournamentAfter":eb,"tournamentStatusChanged":ea["allowed"]!=eb["allowed"]})
    for wid in new_ids:
        w=new_by[wid]
        changes.append({"id":wid,"weapon":w["name"],"type":w["cls"],"new":True,"fields":[],
                        "ttk0m":performance(w),"tournamentAfter":tournament(w),"ttkChanges":[]})
    for wid in removed_ids:
        w=old_by[wid]
        changes.append({"id":wid,"weapon":w["name"],"type":w["cls"],"removed":True,"fields":[],"ttkChanges":[]})
    prev_hash,new_hash=hashof(old),hashof(current)
    is_new_data=prev_hash!=new_hash or hashof(old_zones)!=hashof(new_zones)
    if is_new_data:
        if old:
            archive=DATA/"history"/("weapons-"+prev_hash[:16]+".json")
            if not archive.exists():write(archive,old)
        write(weapon_path,current)
        write(zones_path,new_zones)
    last=read(DATA/"last-changes.json",{"checkedAt":None,"changes":[],"totalChanged":0})
    history=read(DATA/"history"/"index.json",[])
    if not isinstance(history,list):history=[]
    if changes:
        last={"checkedAt":now,"beforeSha256":prev_hash,"afterSha256":new_hash,
              "totalChanged":len(changes),"newCount":len(new_ids),"removedCount":len(removed_ids),"changes":changes,
              "note":"Source values, including firing-mode options, may change without a confirmed EA balance patch."}
        write(DATA/"last-changes.json",last)
        history.insert(0,{"at":now,"count":len(changes),"new":len(new_ids),"removed":len(removed_ids),
                          "weapons":[c["weapon"] for c in changes],"oldHash":prev_hash[:16],"newHash":new_hash[:16]})
        write(DATA/"history"/"index.json",history[:180])
    if not (DATA/"last-changes.json").exists():write(DATA/"last-changes.json",last)
    if not (DATA/"history"/"index.json").exists():write(DATA/"history"/"index.json",[])
    write(DATA/"history-index.json",history[:180])
    write(DATA/"weapon-sync.json",{"schemaVersion":1,"lastCheckedAt":now,"lastDataChangeAt":last.get("checkedAt"),
          "source":SOURCE+"weapons.json","rosterCount":len(current),"rosterSha256":new_hash,
          "currentCheckChanges":len(changes),"lastChangeCount":last.get("totalChanged",0),
          "lastChangeReport":"./data/last-changes.json","status":"ok","automaticSync":True,"tournamentBanThroughMs":201})
    print(json.dumps({"roster":len(current),"checkedAt":now,"sourceUpdated":is_new_data,"numericChanges":len(changes)},indent=2))

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("Unsafe weapon update rejected: "+str(exc),file=sys.stderr)
        raise
