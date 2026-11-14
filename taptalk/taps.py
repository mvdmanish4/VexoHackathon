"""Our own tap detection from the band's raw accelerometer (pure logic, unit-tested).

Why: the band's built-in "double-tap" uses a fixed timing window we cannot change, and on
real bands it often reports one double tap as two single taps (or a tap and a double-tap).
Reading the accelerometer at 833 samples a second gives the exact time of every tap, so we
decide what a double tap is, from the person's own rhythm (see calibrate()).

    TapDetector     raw samples -> one on_tap(t, strength) per real tap
    TapClassifier   tap times   -> on_dot(t) / on_dash(t)
    WristTurn       raw samples -> on_send() when the wrist is turned over and held
    calibrate()     measured gaps -> the double-tap window that splits them
"""
import math
import statistics
import threading


class _LowPass:
    """Exponential low-pass of a 3-vector, correct for uneven sample spacing."""

    def __init__(self, tau):
        self.tau = tau
        self.v = None
        self._t = None

    def feed(self, t, v):
        if self.v is None:
            self.v, self._t = list(v), t
            return self.v
        dt = max(0.0, t - self._t)
        self._t = t
        k = dt / (self.tau + dt) if dt else 0.0
        self.v = [p + k * (x - p) for p, x in zip(self.v, v)]
        return self.v


class TapDetector:
    """A tap is a short, sharp jolt: the acceleration jumps away from its slow average and
    comes back within max_width. Arm swings and wrist turns are slow, so they stay near the
    average, and longer bursts are rejected as movement. After a tap, `refractory` seconds
    of ringing are ignored so one tap never counts twice."""

    def __init__(self, threshold=1.0, max_width=0.05, refractory=0.08, tau=0.05,
                 on_tap=None, on_reject=None):
        self.threshold = threshold      # g above the slow average
        self.max_width = max_width      # s; longer bursts are movement, not taps
        self.refractory = refractory    # s after a tap during which nothing counts
        self.on_tap = on_tap            # (t_peak, strength_g)
        self.on_reject = on_reject      # (t_start, strength_g, width_s), for --debug
        self._lp = _LowPass(tau)
        self._burst = None              # [t_start, peak, t_peak] while above threshold
        self._quiet_until = -math.inf

    def feed(self, t, ax, ay, az):
        lp = list(self._lp.v) if self._lp.v is not None else [ax, ay, az]
        self._lp.feed(t, (ax, ay, az))
        hp = math.sqrt((ax - lp[0]) ** 2 + (ay - lp[1]) ** 2 + (az - lp[2]) ** 2)
        b = self._burst
        if b is None:
            if hp > self.threshold and t >= self._quiet_until:
                self._burst = [t, hp, t]
            return
        if hp > b[1]:
            b[1], b[2] = hp, t
        if hp < self.threshold / 2:
            self._burst = None
            width = t - b[0]
            if width <= self.max_width:
                self._quiet_until = b[2] + self.refractory
                if self.on_tap:
                    self.on_tap(b[2], b[1])
            elif self.on_reject:
                self.on_reject(b[0], b[1], width)
        elif t - b[0] > self.max_width * 4:        # a long push: movement, drop it early
            self._burst = None
            self._quiet_until = t + self.refractory
            if self.on_reject:
                self.on_reject(b[0], b[1], t - b[0])


class TapClassifier:
    """Two taps within double_window = one dash; a tap with no partner = a dot.

    A dot is only known once double_window has passed with no second tap, so call tick()
    often. Every symbol carries the time of its own tap, not the time it was decided.
    Thread-safe: tap() may come from the band's thread, tick() from the main loop."""

    def __init__(self, double_window=0.30, on_dot=None, on_dash=None):
        self.double_window = double_window
        self.on_dot = on_dot
        self.on_dash = on_dash
        self._pending = None
        self._lock = threading.Lock()

    @property
    def pending(self):
        """Time of a tap that may still become a dash, or None."""
        return self._pending

    def tap(self, t):
        out = []
        with self._lock:
            p = self._pending
            if p is not None and t - p <= self.double_window:
                self._pending = None
                out.append(("-", t))
            else:
                if p is not None:
                    out.append((".", p))      # tick() had not run yet: the old tap was a dot
                self._pending = t
        self._emit(out)
        return [s for s, _ in out]

    def tick(self, now):
        out = []
        with self._lock:
            if self._pending is not None and now - self._pending > self.double_window:
                out.append((".", self._pending))
                self._pending = None
        self._emit(out)

    def cancel(self):
        """Forget a waiting tap (it came from turning the wrist to send)."""
        with self._lock:
            self._pending = None

    def _emit(self, out):
        for symbol, t in out:
            fn = self.on_dot if symbol == "." else self.on_dash
            if fn:
                fn(t)


def _angle(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    c = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)) / (na * nb)))
    return math.degrees(math.acos(c))


class WristTurn:
    """Send when the wrist is turned well away from where it rests while tapping, and held.

    It needs no knowledge of how the band is worn: "home" is where gravity points while the
    person taps (learned at every tap), and a send is a turn of more than `send_angle`
    degrees held for `hold` seconds. Taps made while the wrist is turning are not taps."""

    def __init__(self, send_angle=70, start_angle=30, hold=0.5, tau=0.15, on_send=None,
                 on_turn_start=None):
        self.send_angle = send_angle
        self.start_angle = start_angle
        self.hold = hold
        self.on_send = on_send
        self.on_turn_start = on_turn_start
        self._lp = _LowPass(tau)
        self.home = None
        self._home_n = 0
        self._turn_start = None     # time the wrist left home (angle > start_angle)
        self._over_since = None     # time the angle passed send_angle
        self._sent = False          # wait for the wrist to come back before sending again

    @property
    def angle(self):
        if self.home is None or self._lp.v is None:
            return 0.0
        return _angle(self.home, self._lp.v)

    @property
    def turning(self):
        """True while the wrist is away from home (taps then are not taps)."""
        return self._turn_start is not None

    def note_tap(self):
        """The person just tapped, so the wrist is at home: learn that direction."""
        g = self._lp.v
        if g is None or self._turn_start is not None:
            return
        if self.home is None:
            self.home, self._home_n = list(g), 1
            return
        self._home_n = min(self._home_n + 1, 10)
        k = 1.0 / self._home_n
        self.home = [h + k * (x - h) for h, x in zip(self.home, g)]

    def feed(self, t, ax, ay, az):
        g = self._lp.feed(t, (ax, ay, az))
        if self.home is None:
            return
        ang = _angle(self.home, g)
        if ang > self.start_angle:
            if self._turn_start is None:
                self._turn_start = t
                if self.on_turn_start:
                    self.on_turn_start(t)
        elif ang < self.start_angle * 0.7:
            self._turn_start = None
            self._sent = False
        if ang > self.send_angle and not self._sent:
            if self._over_since is None:
                self._over_since = t
            elif t - self._over_since >= self.hold:
                self._sent = True
                self._over_since = None
                if self.on_send:
                    self.on_send()
        else:
            self._over_since = None


def _split(gaps):
    """Split gaps into (short, long) at the largest jump between sorted values (by ratio)."""
    g = sorted(gaps)
    best, at = 0.0, len(g)
    for i in range(len(g) - 1):
        r = g[i + 1] / max(g[i], 1e-6)
        if r > best:
            best, at = r, i + 1
    return g[:at], g[at:]


def calibrate(single_taps, double_taps, lo=0.15, hi=0.6):
    """single_taps: times of separate single taps; double_taps: times of the taps made as
    double taps (two per double tap). Returns (double_window, report); report["ok"] is
    False when the two rhythms overlap, with report["why"] saying what to change."""
    s = sorted(single_taps)
    d = sorted(double_taps)
    dot_gaps = [b - a for a, b in zip(s, s[1:])]
    pair_gaps = [b - a for a, b in zip(d, d[1:])]
    if len(dot_gaps) < 2 or len(pair_gaps) < 3:
        return None, {"ok": False, "why": "not enough taps were felt (%d single, %d double)"
                      % (len(s), len(d))}
    inner, _ = _split(pair_gaps)
    slowest_double = max(inner)
    fastest_dot = min(dot_gaps)
    window = math.sqrt(slowest_double * fastest_dot)   # the middle of two timings
    window = max(lo, min(hi, window))
    report = {
        "ok": slowest_double < fastest_dot,
        "double_gap": statistics.median(inner),
        "slowest_double": slowest_double,
        "dot_gap": statistics.median(dot_gaps),
        "fastest_dot": fastest_dot,
        "window": window,
    }
    if not report["ok"]:
        report["why"] = ("some single taps (%.2f s apart) were as quick as a double tap "
                         "(%.2f s): leave a little more time between single taps"
                         % (fastest_dot, slowest_double))
    return window, report
