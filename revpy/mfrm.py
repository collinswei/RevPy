import numpy as np
from copy import deepcopy
from scipy.linalg import solve
from revpy.exceptions import InvalidInputParameters

"""
Multi-flight recapture method is a simple heuristics that allows to estimate
unconstrained demand considering market recapture effects across multiple
flights and fare classes.

This implementation is based on paper by Richard M. Ratliff "A multi-flight
recapture heuristic for estimating unconstrained demandx from
airline bookings", Journal of Revenue and Pricing Management (2008)

NOTE: current implementation introduces `calibrate_no_booking` method that
is not part of the original paper
"""


def estimate_host_level(observed, availability, probs, nofly_prob):
    """ Estimate demand, spill and recapture using multi-flight recapture
    method (MFRM) on host-level

    Parameters
    ----------
    observed: dict
        Observed demand for each product
    availability: dict
        Availability of demand open during period considered
    probs: dict
        Customer selection probability for a product
    nofly_prob: float
        "Do not fly" probability


    Returns
    -------
    tuple
        Estimated demand, spill and recapture for H
    """

    demand = spill = recapture = 0

    if probs:
        # probability of selecting an open element from market set M
        prob_market_open = nofly_prob + sum([pr * availability.get(p, 0)
                                             for p, pr in probs.items()])

        recapture_rate = (prob_market_open - nofly_prob) / prob_market_open

        # probability of selecting a closed element from host set H
        prob_host_closed = (1 - prob_market_open) / (1 - nofly_prob)

        # total observed demand
        total_odemand = sum(observed.values())
        demand, spill, recapture = demand_mass_balance_h(total_odemand,
                                                         prob_host_closed,
                                                         recapture_rate)
    return demand, spill, recapture


def estimate_class_level(observed, availability, probs, nofly_prob,
                         calibrate=True):
    """ Estimate demand, spill and recapture using multi-flight recapture
    method (MFRM) on class-level

    Parameters
    ----------
    observed: dict
        Observed demand for each product
    availability: dict
        Availability of demand open during period considered
    probs: dict
        Customer selection probability for a product
    nofly_prob: float
        "Do not fly" probability

    Returns
    -------
    tuple
        Estimated demand, spill and recapture for H
    """

    host_estimates = estimate_host_level(observed, availability, probs,
                                         nofly_prob)
    _, host_spill, host_recapture = host_estimates

    estimates = {}
    total_odemand = sum(observed.values())

    for product in probs.keys():
        odemand = observed.get(product, 0)
        avail = availability.get(product, 0)

        if avail == 0 and odemand > 0:
            raise InvalidInputParameters('Non zero observed demand with '
                                         'zero availability')

        if odemand:
            estimate = demand_mass_balance_c(total_odemand, odemand, avail,
                                             host_recapture)
            estimates[product] = {
                'demand': estimate[0],
                'spill': estimate[1],
                'recapture': estimate[2]
            }
        else:
            estimates[product] = {
                'demand': 0,
                'spill': 0,
                'recapture': 0
            }

    if calibrate:
        estimates = calibrate_no_booking(estimates, observed, availability,
                                         probs, host_spill)
    return estimates


def calibrate_no_booking(estimates, observed, availability, probs, host_spill):
    """Demand mass balance equation has many solution in case of observed
    demand is 0. If observed demand is 0, then unconstrained demand equal
    spill and recapture is 0. This method redictrobite unaccounted spill
    proportionally between 0-deman products

    Parameters
    ----------
    estimates: dict
        Demand, spill and recapture estimated by estimate_class_level
    observed: dict
        Observed demand for each product
    availability: dict
        Availability of demand open during period considered
    probs: dict
        Customer selection probability for a product
    host_spill: float
        Estimated host level spill

    Returns
    -------
    tuple
        Estimated demand, spill and recapture for H
    """

    estimates = deepcopy(estimates)

    class_spill = sum([e['spill'] for e in estimates.values()])

    # unaccounted spill - difference between host level spill and
    # sum spill for all products
    unaccounted_spill = host_spill - class_spill

    if unaccounted_spill > 0:
        # products with no observed bookings
        observed = [k for k in estimates.keys() if observed.get(k, 0) == 0]

        # weight of each product
        weights = {p: probs[p] * (1 - availability.get(p, 0))
                   for p in observed}

        # normalized weights
        weights = {p: w / sum(weights.values()) for p, w in weights.items()}

        for p, w in weights.items():
            estimates[p]['spill'] = unaccounted_spill * w
            estimates[p]['demand'] = unaccounted_spill * w

    return estimates


def selection_probs(utilities, market_share):
    """Customer selection probability for all products and 'do not fly'

    Parameters
    ----------
    utilities: dict
        Utilities of products based on choice model parameters
    market_share: float
        Host's market share

    Returns
    -------
    tuple
        Selection probs for each product and 'do not fly' prob
    """

    exp_sum = sum([np.exp(u) for u in utilities.values()])
    exp_nofly_utility = exp_sum * (1 - market_share) / market_share
    exp_sum += exp_nofly_utility

    # customer selection probability for all products
    probs = {p: (np.exp(u) / exp_sum) for p, u in utilities.items()}

    # customer selection probability for ‘do not fly’
    nofly_prob = exp_nofly_utility / exp_sum

    return probs, nofly_prob


def demand_mass_balance_c(host_odemand, class_odemand, avail, host_recapture):
    """Solve Demand Mass Balance equation for class-level

    Parameters
    ----------
    host_odemand: int
        Observerd host demand
    class_odemand: int
        Observed class demand
    avail: dict
        Availability of demand open during period considered
    host_recapture: float
        Estimated host level recapture

    Returns
    -------
    tuple
        Estimated demand, spill and recapture
    """

    # if observed demand of a class is 0 demand mass balance can't
    # estimate demand and spill alone without additioanl information
    demand = spill = recapture = 0
    if class_odemand:
        recapture = host_recapture * class_odemand / host_odemand

        # availability of demand closed during period considered
        k = 1 - avail
        A = np.array([[1, -1], [-k, 1]])
        B = np.array([class_odemand - recapture, 0])
        demand, spill = solve(A, B)

    return demand, spill, recapture


def demand_mass_balance_h(odemand, close_prob, recapture_rate):
    """Solve Demand Mass Balance equation for host-level

    Parameters
    ----------
    odemand: int
        Observerd demand
    close_prob: float
        Probability of selecting a closed element from host set H
    recapture_rate: float
        Estimated recapture rate

    Returns
    -------
    tuple
        Estimated demand, spill and recapture
    """

    A = np.array([[1, -1, 1], [-close_prob, 1, 0], [0, -recapture_rate, 1]])
    B = np.array([odemand, 0, 0])

    demand, spill, recapture = solve(A, B)

    return demand, spill, recapture
