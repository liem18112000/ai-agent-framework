"""Topic Adherence — does the G5 explore loop stay on-seed round over round?

The loop derives round-N focus from round N-1's node titles, which can drift into the memory
gravity well. Given each round's focus terms and the seed's own topic terms, `adherence` is the
fraction of focus terms still on-topic; `adherence_curve` plots it per round — a monotone decline
is drift, and the round where it falls off a cliff is where to cap KGA_EXPLORE_MAX_ROUNDS.
"""

from __future__ import annotations


def adherence(round_terms: list[str], seed_terms: set[str]) -> float:
    """Fraction of a round's focus terms that are on the seed's topic. 1.0 = fully on-topic."""
    if not round_terms:
        return 1.0
    seed_lower = {s.lower() for s in seed_terms}
    hit = sum(any(s in t.lower() or t.lower() in s for s in seed_lower) for t in round_terms)
    return hit / len(round_terms)


def adherence_curve(rounds: list[list[str]], seed_terms: set[str]) -> list[float]:
    return [adherence(r, seed_terms) for r in rounds]
