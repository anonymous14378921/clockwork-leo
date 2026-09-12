# E1 Results

## Verdict: **PASS** (HA2 confirmed, topology-class framing survives)

Star and Delta induce materially different path-cost **structure**. The
difference is not in average path length (the classes are comparable there); it
is exactly the two structural features the brief named: a **seam tax** for Star
and a **latitude cap** for Delta.

## Seam tax (the pure topology-class effect)

Measured on the controlled pair (`ctrl-star`, `ctrl-delta`), identical in every
parameter except RAAN span, so inclination and size are held equal and only the
class differs:

| pair | seam/wrap p95 (hops) | seam max |
|------|----------------------|----------|
| ctrl-star  | **43** | 43 |
| ctrl-delta | **2**  | 2  |

**Ratio 21.5x**, from flipping RAAN span pi to 2pi alone. The real
constellations echo it: seam p95 is 47 (ref-star) and 34 (OneWeb) for the Star
class, versus 1 (Starlink) and 2 (Kuiper) for the Delta class. A Star's
first and last planes counter-rotate and are unlinked, so a physically adjacent
cross-seam pair routes around the whole cylinder; a Delta wraps as a torus and
pays nothing.

## Latitude cap (co-travels with Delta in practice)

Mean satellites per latitude band over one orbital period (12 snapshots):

| constellation | inclination | equatorial | mid | **arctic** |
|---------------|-------------|-----------|-----|-----------|
| ref-star (Star) | 87.0 | 118 | 352 | **274** |
| oneweb (Star)   | 87.9 |  66 | 196 | **154** |
| starlink (Delta)| 53.0 | 216 | 888 | **0** |
| kuiper (Delta)  | 51.9 | 170 | 646 | **0** |

The Delta class cannot cover the Arctic at all (nothing flies above its
inclination). This is an inclination effect, but it co-travels with the class
because Deltas are deployed at moderate inclination, so it is decisive for the
maritime/Arctic workflow where the AoI sits above the Delta line.

## Path cost and capable sparsity (context, not discriminators)

Mean/p95 path cost is similar across classes (p95 hops 25 to 41; p95 ms 77 to
103), which is the honest point: the classes are told apart by **structure**
(seam tax, coverage cap), not by average cost. Capable-node sparsity (HB2) is
confirmed and is class-independent: hops to the nearest capable node grow from 0
at p=1 to about 6 (mean) and 11 to 12 (p95) at p=0.01 for both a Star and a Delta.
E0's k=7 detour at p=0.02 sits right on this curve.

## Honesty notes

- The seam is shown causally (controlled pair, inclination fixed). The latitude
  cap is an inclination property that co-travels with the Delta class, not a
  consequence of the torus itself. RESULTS states both plainly rather than
  merging them.
- Latitude coverage is exact under the static-snapshot model (Earth rotation
  does not change latitudes). Named longitude regions would need ground tracks;
  E1 reports latitude bands, averaged over snapshots, which is what the
  coverage-cap claim needs.

## Reproduce

    just run e1_substrate
    just figures e1_substrate   # -> figures/e1_substrate.{pdf,png}
