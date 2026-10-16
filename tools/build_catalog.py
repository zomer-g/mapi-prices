"""Group SKUs, price-list rows and price-committee decisions into general products.

Reads data/base.js (window.DATA) and, if present, data/pricelist_2026.csv.
Writes data/catalog.js (window.CATALOG).

A general product is what links the sources together:
  * every price-list product name (all its variants, in every year) is one product;
  * a SKU that is linked to a price-list row joins that product;
  * a SKU with no price-list link joins the committee products it is linked to;
  * SKUs with the same name (ignoring spaces and punctuation) are one product;
  * committee decisions that no sale is linked to join the product that already
    holds a decision with the same product name, or become a product of their own.
A committee decision linked to SKUs in several products appears in each of them.

Run: python3 tools/build_catalog.py
"""
import csv
import json
import os
import re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY_2026 = '2026-10-16'  # the date the 2026 price list was checked; shown next to its name

src = open(os.path.join(ROOT, 'data', 'base.js'), encoding='utf-8').read()
D = json.loads(src[src.index('{'):src.rindex('}') + 1])
P, L24, L25, R = D['P'], D['L24'], D['L25'], D['R']

# ---- price lists: one list of rows per edition ----
EDITIONS = [
    {'y': 2024, 'label': 'מחירון 2024', 'date': '2024-01-01', 'doc': 'docs/pricelist-2024.pdf'},
    {'y': 2025, 'label': 'מחירון 2025', 'date': '2025-01-01', 'doc': 'docs/pricelist-2025.pdf'},
]
L24idx = {r['id']: r for r in L24}
rows = []  # {ed, id, pg, p, v, pr, u, nt}
for r in L24:
    rows.append({'ed': 2024, 'id': r['id'], 'pg': r['pg'], 'p': r['p'], 'v': r['v'], 'pr': r['pr'], 'u': r.get('u', ''), 'nt': r.get('nt', '')})
for r in L25:
    a = L24idx.get(r['id'])
    rows.append({'ed': 2025, 'id': r['id'], 'pg': r['pg'], 'p': r['p'], 'v': r['v'], 'pr': r['pr'],
                 'u': r.get('u') or (a or {}).get('u', ''), 'nt': r.get('nt', '')})

f26 = os.path.join(ROOT, 'data', 'pricelist_2026.csv')
if os.path.exists(f26):
    EDITIONS.append({'y': 2026, 'label': 'מחירון 2026', 'date': TODAY_2026, 'checked': TODAY_2026,
                     'doc': 'docs/pricelist-2026.pdf'})
    by_pv = {(r['p'], r['v']): r['id'] for r in L24 + L25}
    with open(f26, encoding='utf-8-sig') as fh:
        for i, r in enumerate(csv.DictReader(fh)):
            pr = r['price_ils'].replace(',', '').strip()
            rows.append({'ed': 2026, 'id': by_pv.get((r['product'], r['variant']), 'N26_%d' % i),
                         'pg': int(r['page']) if r['page'].strip().isdigit() else r['page'],
                         'p': r['product'], 'v': r['variant'], 'pr': float(pr) if pr else None,
                         'u': r.get('unit', ''), 'nt': r.get('notes', '')})

# ---- union-find over SKUs, price-list product names and committee product names ----
par = {}


def find(x):
    par.setdefault(x, x)
    while par[x] != x:
        par[x] = par[par[x]]
        x = par[x]
    return x


def union(a, b):
    par[find(a)] = find(b)


Ridx = {r['id']: r for r in R}
for r in rows:
    find('L:' + r['p'])
for p in P:
    m = 'M:%s' % p['m']
    find(m)
    for i in p['pl']:
        union(m, 'L:' + L24idx[i]['p'])
same_name = {}
for p in P:
    key = re.sub(r'[^\w]', '', p['d'].replace('_', ''))
    if key in same_name:
        union('M:%s' % p['m'], same_name[key])
    else:
        same_name[key] = 'M:%s' % p['m']
for p in P:
    if not p['pl']:
        for i in p['pr']:
            union('M:%s' % p['m'], 'R:' + Ridx[i]['p'])
r_groups = defaultdict(set)  # R id -> group roots (via its SKUs)
for p in P:
    for i in p['pr']:
        r_groups[i].add('M:%s' % p['m'])
for r in R:
    if r['id'] not in r_groups:
        find('R:' + r['p'])

members = defaultdict(list)
for x in list(par):
    members[find(x)].append(x)

Pby = {p['m']: p for p in P}
groups = []
gid_of = {}
for root, ms in members.items():
    skus = sorted((Pby[int(x[2:])] for x in ms if x.startswith('M:')), key=lambda p: -p['t'])
    lnames = [x[2:] for x in ms if x.startswith('L:')]
    rnames = [x[2:] for x in ms if x.startswith('R:')]
    if len(lnames) == 1:
        name = lnames[0]
    elif skus:
        name = skus[0]['d']
    else:
        name = (lnames or rnames)[0]
    cat = skus[0]['c'] if skus else next((r['cat'] for r in L24 if r['p'] in lnames), '')
    g = {'id': 'g%d' % (len(groups) + 1), 'name': name, 'cat': cat,
         'k': skus[0].get('k') if skus else None,
         'skus': [p['m'] for p in skus], 'pl': [], 'pr': []}
    groups.append(g)
    for x in ms:
        gid_of[x] = g

for r in rows:
    gid_of['L:' + r['p']]['pl'].append(r)
for r in R:
    if r['id'] in r_groups:
        gs = {gid_of[find(m)]['id']: gid_of[find(m)] for m in r_groups[r['id']]}
        for g in gs.values():
            g['pr'].append(r['id'])
for r in R:
    if r['id'] not in r_groups:
        key = 'R:' + r['p']
        g = gid_of.get(key)
        same = next((g2 for g2 in groups if g2 is not g and any(Ridx[i]['p'] == r['p'] for i in g2['pr'])), None)
        (same or g)['pr'].append(r['id'])
groups = [g for g in groups if g['skus'] or g['pl'] or g['pr']]

# stable ids: biggest revenue first
for g in groups:
    g['t'] = round(sum(Pby[m]['t'] for m in g['skus']), 2)
    g['n'] = sum(Pby[m]['n'] for m in g['skus'])
groups.sort(key=lambda g: (-g['t'], g['name']))
for i, g in enumerate(groups):
    g['id'] = 'g%d' % (i + 1)

out = {'editions': EDITIONS, 'groups': groups}
with open(os.path.join(ROOT, 'data', 'catalog.js'), 'w', encoding='utf-8') as fh:
    fh.write('// generated by tools/build_catalog.py\nwindow.CATALOG = ')
    json.dump(out, fh, ensure_ascii=False, separators=(',', ':'))
    fh.write(';\n')

n_sku = sum(len(g['skus']) for g in groups)
assert n_sku == len(P), (n_sku, len(P))
print('%d products, %d SKUs, %d price-list rows, %d committee rows' % (
    len(groups), n_sku, sum(len(g['pl']) for g in groups), len({i for g in groups for i in g['pr']})))
