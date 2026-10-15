"""Operating characteristics of the final verdict() (plan_final §7) under eval3c noise.
Noise pool: eval3c full−nokg per-question single-run diffs on the 39 questions (36 identical ctx),
coverage & strict drawn jointly, centered. Models: E = exchangeable draws per (q,rep);
Q = question-specific (each arm draws full_j or nokg_j per rep; lower-noise bound)."""
import json, sys
import numpy as np
from scipy import stats
R = '/mnt/ollama-data/bible_rag_store/reports/eval3c_20261014/'
L = lambda f: {s['question_id']: s for s in json.load(open(R + f))['samples']}
F, N = L('full.faith_cov.json'), L('nokg.faith_cov.json')
b = json.load(open(sys.argv[1]))
ids = [x['qid'] for x in b]
fc = np.array([F[i]['coverage'] for i in ids]); nc = np.array([N[i]['coverage'] for i in ids])
fs = np.array([F[i]['ragas_faithfulness_strict'] for i in ids]); ns = np.array([N[i]['ragas_faithfulness_strict'] for i in ids])
dc0 = (fc - nc) - (fc - nc).mean(); ds0 = (fs - ns) - (fs - ns).mean()
rng = np.random.default_rng(20261015)
S, P = 3000, 2000
ALPHA_H = 0.05 / 3          # Holm worst-case step for 3 comparisons
COV_M, STR_M = -0.05, -0.04

def tlo(x):  # two-sided 97.5% t-CI lower bound, x shape (S, n)
    n = x.shape[1]; return x.mean(1) - stats.t.ppf(1 - 0.0125, n - 1) * x.std(1, ddof=1) / np.sqrt(n)

def signflip_p(x):  # two-sided MC sign-flip p, vectorized over sims
    n = x.shape[1]; obs = np.abs(x.mean(1))
    cnt = np.zeros(x.shape[0])
    for _ in range(P // 500):
        sg = rng.choice([-1.0, 1.0], size=(500, n))
        perm = np.abs(x @ sg.T / n)              # (S, 500)
        cnt += (perm >= obs[:, None] - 1e-12).sum(1)
    return (cnt + 1) / (P + 1)

def draw(model, n, rc, sd_scale):
    dc = dc0 * sd_scale
    if model == 'E':
        j = rng.integers(0, len(ids), (S, n, rc))
        c = dc[j].mean(2); s = ds0[j[:, :, :3]].mean(2)
    else:
        j = rng.integers(0, len(ids), (S, n))
        cf, cn = fc[j][..., None], nc[j][..., None]
        sf, sn = fs[j][..., None], ns[j][..., None]
        pa = rng.integers(0, 2, (S, n, rc)); pb = rng.integers(0, 2, (S, n, rc))
        armc = np.where(pa, cf, cn); ctlc = np.where(pb, cf, cn)
        arms = np.where(pa[..., :3], sf, sn); ctls = np.where(pb[..., :3], sf, sn)
        c = ((armc - ctlc) * sd_scale).mean(2); s = (arms - ctls).mean(2)
    return c, s

def oc(model, n, rc, dcov, dstr, sd_scale=1.0):
    c, s = draw(model, n, rc, sd_scale); c = c + dcov; s = s + dstr
    harm = ((signflip_p(c) < ALPHA_H) & (c.mean(1) < 0)) | ((signflip_p(s) < ALPHA_H) & (s.mean(1) < 0))
    ok = (tlo(c) > COV_M) & (tlo(s) > STR_M) & ~harm
    return dict(adopt=round(ok.mean(), 3), harm=round(harm.mean(), 3), inconcl=round(1 - ok.mean() - harm.mean(), 3))

out = {'pool_sd_cov': round(float(np.std(fc - nc, ddof=1)), 4), 'pool_sd_strict': round(float(np.std(fs - ns, ddof=1)), 4)}
for model in ('E', 'Q'):
    for n in (19, 20, 39):
        for rc in (3, 6):
            for dcov, dstr in ((0, 0), (0.03, 0), (-0.05, 0), (-0.08, 0), (0, -0.04)):
                k = f'{model}|n{n}|Rc{rc}|dcov{dcov:+.2f}|dstr{dstr:+.2f}'
                out[k] = oc(model, n, rc, dcov, dstr); print(k, out[k], flush=True)
for sd in (0.12, 0.19):
    for n in (20, 39):
        for dcov in (0, -0.05):
            k = f'E|n{n}|Rc6|dcov{dcov:+.2f}|sd{sd}'
            out[k] = oc('E', n, 6, dcov, 0, sd / float(np.std(fc - nc, ddof=1))); print(k, out[k], flush=True)
json.dump(out, open(sys.argv[2], 'w'), indent=1)
