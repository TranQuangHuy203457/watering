#!/usr/bin/env python3
"""
Extract temperature, humidity, light (proxy) and timestamp every 3 hours from a Tomorrow.io-like JSON timeline.
Usage:
  python scripts/extract_3hr.py input.json -o out.csv

Behavior:
- Looks for the first timeline array under `timelines` (e.g., minutely/hourly).
- Selects the first entry, then the next entry at >= 3 hours after the last selected, and so on.
- Temperature -> `values.temperature`
- Humidity -> `values.humidity`
- Light proxy: prefers `values.uvIndex`, then `values.visibility`, then `values.cloudCover` (note: choose appropriate field for your meaning of "ánh sáng").
- Outputs CSV with columns: time,temperature,humidity,light
"""
import argparse
import json
from datetime import datetime, timezone, timedelta
import csv

PREFERRED_LIGHT_KEYS = ['uvIndex', 'visibility', 'solarGhi', 'cloudCover']


def parse_iso(ts):
    # handle trailing Z
    if ts.endswith('Z'):
        ts = ts[:-1] + '+00:00'
    return datetime.fromisoformat(ts)


def find_timeline(data):
    if not isinstance(data, dict):
        raise ValueError('JSON root must be an object')
    tl = data.get('timelines')
    if not tl:
        # fallback: maybe top-level is a list
        for k in data:
            if isinstance(data[k], list) and len(data[k]) and 'time' in data[k][0]:
                return data[k]
        raise ValueError('No timelines found in JSON')
    # timelines is a dict of arrays; pick first non-empty
    for key in tl:
        arr = tl[key]
        if isinstance(arr, list) and arr:
            return arr
    raise ValueError('timelines found but no non-empty array present')


def get_light_value(values):
    for k in PREFERRED_LIGHT_KEYS:
        if k in values:
            return values[k]
    return ''


def sample_every_3h(timeline):
    out = []
    last = None
    for entry in timeline:
        t = parse_iso(entry['time'])
        vals = entry.get('values', {})
        if last is None:
            out.append((t, vals))
            last = t
        else:
            if (t - last) >= timedelta(hours=3):
                out.append((t, vals))
                last = t
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('input', help='input JSON file')
    p.add_argument('-o', '--out', help='output CSV file', required=True)
    args = p.parse_args()

    with open(args.input, 'r', encoding='utf-8') as f:
        data = json.load(f)

    timeline = find_timeline(data)
    sampled = sample_every_3h(timeline)

    with open(args.out, 'w', newline='', encoding='utf-8') as csvf:
        w = csv.writer(csvf)
        w.writerow(['time','temperature','humidity','light'])
        for t, vals in sampled:
            temp = vals.get('temperature','')
            hum = vals.get('humidity','')
            light = get_light_value(vals)
            w.writerow([t.isoformat(), temp, hum, light])

    print(f'Wrote {len(sampled)} samples to {args.out}')

if __name__ == '__main__':
    main()
