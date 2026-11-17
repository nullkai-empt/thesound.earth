import json
import numpy as np
from pathlib import Path
from aetherwaves.blocks import group_days_into_blocks

REGIONS_PATH = 'config/regions.json'
with open(REGIONS_PATH, 'r', encoding='utf-8') as f:
    cfg = json.load(f)

hold_thresh = cfg['defaults'].get('hold_threshold', 0.013)
enabled_regions = [r for r in cfg['regions'] if r.get('enabled', True)]

results = []
for r in enabled_regions:
    rid = r['id']
    name = r.get('name', rid)
    if rid == 'gulf_stream':
        p = Path('data/raw_oscar/oscar_2025_daily.json')
    else:
        p = Path(f'data/raw_oscar/regions/{rid}/oscar_2025_daily.json')
    
    records = json.loads(p.read_text(encoding='utf-8'))
    total_days = len(records)
    
    none_days = sum(1 for rec in records if rec.get('speed_p95') is None)
    valid_days = total_days - none_days
    pct_none = (none_days / total_days) * 100.0 if total_days else 0.0
    
    valid_speeds = [rec['speed_p95'] for rec in records if rec.get('speed_p95') is not None]
    if valid_speeds:
        p5 = float(np.percentile(valid_speeds, 5))
        p95 = float(np.percentile(valid_speeds, 95))
        mean_speed = float(np.mean(valid_speeds))
    else:
        p5, p95, mean_speed = None, None, None
        
    blocks = group_days_into_blocks(records, block_size=7)
    total_blocks = len(blocks)
    held_blocks = sum(1 for b in blocks if b.get('magnitude') is not None and b['magnitude'] < hold_thresh)
    pct_held = (held_blocks / total_blocks) * 100.0 if total_blocks else 0.0
    
    results.append({
        'id': rid,
        'name': name,
        'total_days': total_days,
        'valid_days': valid_days,
        'pct_none': pct_none,
        'p5': p5,
        'p95': p95,
        'mean_speed_p95': mean_speed,
        'total_blocks': total_blocks,
        'held_blocks': held_blocks,
        'pct_held': pct_held
    })

header = f"| {'Region ID':20s} | {'Valid Days':10s} | {'% None':8s} | {'P5':8s} | {'P95':8s} | {'Mean speed':12s} | {'% Blocks Held':14s} |"
sep = '|' + '-'*22 + '|' + '-'*12 + '|' + '-'*10 + '|' + '-'*10 + '|' + '-'*10 + '|' + '-'*14 + '|' + '-'*16 + '|'
print(header)
print(sep)
for res in results:
    p5_str = f"{res['p5']:.4f}" if res['p5'] is not None else "N/A"
    p95_str = f"{res['p95']:.4f}" if res['p95'] is not None else "N/A"
    mean_str = f"{res['mean_speed_p95']:.4f}" if res['mean_speed_p95'] is not None else "N/A"
    line = f"| {res['id']:20s} | {res['valid_days']:4d}/{res['total_days']:3d}    | {res['pct_none']:6.2f}% | {p5_str:8s} | {p95_str:8s} | {mean_str:12s} | {res['held_blocks']:2d}/{res['total_blocks']:2d} ({res['pct_held']:5.1f}%) |"
    print(line)
