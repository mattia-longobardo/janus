# Spike E0: dnsmasq with a tagged guest dhcp-range

Question: if the Pi-hole provider adds a tagged guest range and a MAC-only
`dhcp-host` line next to the untagged quarantine range Pi-hole already
generates, does a guest always get a guest-pool address, never a quarantine one?

## Result: variant A confirmed

Janus only adds two lines (via `misc.dnsmasq_lines`); the Pi-hole generated
quarantine range stays untouched, so cutover/rollback is unaffected.

```
dhcp-host=<guest mac>,set:guest,<hostname>,<lease>
dhcp-range=tag:guest,<guest start>,<guest end>,<lease>
```

Context reproduced in the spike (what Pi-hole generates, not written by Janus):

```
dhcp-range=10.99.0.240,10.99.0.254,1h        # untagged quarantine
dhcp-option=option:router,10.99.0.1          # network router
dhcp-option=tag:!known,option:router         # empty value: unknown clients get no router
```

Findings:

- The `dhcp-host` line must carry the MAC only (no IP): it makes the client
  "known" and sets tag `guest`; dnsmasq then picks the `tag:guest` range.
- Guests receive the router option (10.99.0.1): `tag:!known,option:router`
  does not apply to known clients.
- Control client (unknown MAC) lands in quarantine (10.99.0.250) and gets no
  router, as expected.
- Variant B (quarantine tagged `tag:!known`) also works (2 runs) but is not
  needed: it would force Janus to own both ranges and disable Pi-hole's own.

## Output (`VARIANT=A RUNS=5 ./run.sh`, dnsmasq 2.92rel2, lease file cleared each run)

```
run 1: guest    ip=10.99.0.224 router=10.99.0.1
run 1: stranger ip=10.99.0.250 router=NONE
run 2: guest    ip=10.99.0.224 router=10.99.0.1
run 2: stranger ip=10.99.0.250 router=NONE
run 3: guest    ip=10.99.0.224 router=10.99.0.1
run 3: stranger ip=10.99.0.250 router=NONE
run 4: guest    ip=10.99.0.224 router=10.99.0.1
run 4: stranger ip=10.99.0.250 router=NONE
run 5: guest    ip=10.99.0.224 router=10.99.0.1
run 5: stranger ip=10.99.0.250 router=NONE
```

Variant B (`VARIANT=B RUNS=2`): identical output.

## Caveats

- Tested against Alpine's dnsmasq 2.92, not Pi-hole FTL's embedded dnsmasq
  (FTL v6 tracks recent dnsmasq 2.9x; tag/known semantics are old and stable,
  but verify on the real Pi-hole during cutover).
- The address inside a range is hash-of-MAC based, hence the same IP on every
  run; what is verified is the range choice, not address variety.
- Only one guest MAC and one control MAC were exercised.
- Uses an isolated bridge network (`janus-dnsmasq-spike`, 10.99.0.0/24) and
  throwaway `janus-spike-*` containers, all removed on exit; needs Docker and
  network access to pull `alpine:3` and `apk add dnsmasq`.
