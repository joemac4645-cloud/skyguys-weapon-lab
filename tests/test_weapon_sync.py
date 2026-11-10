import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("weapon_sync",ROOT/"scripts"/"sync_weapons.py")
sync=importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

def weapon(rpm=800,damage=35.22,category="SMG",name="Test gun"):
    return {"id":"unit","name":name,"cls":category,"rpm":rpm,"mag":31,"fireMode":"auto",
            "dmg":[{"r":0,"d":damage},{"r":9,"d":damage},{"r":9,"d":26.05},{"r":75,"d":26.05}]}

class WeaponSyncTests(unittest.TestCase):
    def test_three_and_four_shot_math(self):
        w=weapon()
        self.assertEqual(sync.performance(w,0)["btk"],3)
        self.assertEqual(sync.performance(w,0)["ttkMs"],150)
        self.assertEqual(sync.performance(w,10)["btk"],4)
        self.assertEqual(sync.performance(w,10)["ttkMs"],225)

    def test_exact_damage_dropoff_boundary(self):
        w=weapon()
        self.assertEqual(sync.damage_at(w,9),35.22)
        self.assertEqual(sync.damage_at(w,9.00001),26.05)

    def test_201_ms_included_in_bans(self):
        self.assertFalse(sync.tournament(weapon(rpm=600))["allowed"])
        self.assertFalse(sync.tournament(weapon(rpm=599))["allowed"])  # Displays 200 ms.
        self.assertTrue(sync.tournament(weapon(rpm=590))["allowed"])  # Displays 203 ms.
        self.assertFalse(sync.tournament(weapon(category="DMR",rpm=300))["allowed"])
        self.assertFalse(sync.tournament(weapon(category="Sniper Rifle",rpm=300))["allowed"])
        self.assertTrue(sync.tournament(weapon(category="Sniper Rifle",name="Interdictor",rpm=300))["allowed"])

    def test_only_numeric_and_firing_fields_trigger_report(self):
        w=weapon()
        v=copy.deepcopy(w)
        v["description"]="Editorial change"
        self.assertEqual(sync.fields(w,v),[])
        v["rpm"]=790
        self.assertEqual(sync.fields(w,v)[0]["field"],"rpm")

    def test_reject_truncated_data(self):
        x=[weapon()]
        zones={"weapons":{"unit":{"headshot":1.8,"limb":.84}}}
        with self.assertRaises(ValueError):
            sync.validate(x,zones,[])


    def test_ea_2120_interim_ranges(self):
        scw={"id":"scw10","name":"SCW-10","cls":"SMG","rpm":799.999,"fireMode":"auto",
             "dmg":[{"r":r,"d":d} for r,d in
             [(0,35.22),(9,35.22),(9,26.05),(21,26.05),(21,20.67),
              (36,20.67),(36,17.13),(75,17.13),(75,14.62)]]}
        scout={"id":"miniscout","name":"Mini Scout","cls":"Sniper Rifle","rpm":47,
               "dmg":[{"r":r,"d":d} for r,d in [(0,62),(21,62),(75,58)]]}
        matched=sync.official_patch_interims([scw,scout])
        self.assertEqual(matched,["SCW-10","Mini Scout"])
        self.assertEqual(sync.damage_at(scw,54),17.13)
        self.assertEqual(sync.damage_at(scw,55.001),14.3)
        self.assertEqual(sync.damage_at(scw,75.001),12.76)
        self.assertEqual(sync.performance(scw,54)["btk"],6)
        self.assertEqual(sync.performance(scw,55.001)["btk"],7)
        self.assertEqual(sync.performance(scw,75.001)["btk"],8)
        self.assertAlmostEqual(sync.performance(scw,55.001)["ttkMs"],450.0006,places=2)
        self.assertEqual(sync.damage_at(scout,150),58)
        self.assertEqual(sync.damage_at(scout,150.001),50)
        self.assertEqual(sync.performance(scout,150.001)["btk"],2)
        self.assertEqual(sync.official_patch_interims([scw,scout]),[])

if __name__=="__main__":
    unittest.main()
