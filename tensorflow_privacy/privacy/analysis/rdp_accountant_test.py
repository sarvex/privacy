# Copyright 2018 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for rdp_accountant.py."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import math
import sys

from absl.testing import parameterized
from mpmath import exp
from mpmath import inf
from mpmath import log
from mpmath import npdf
from mpmath import quad
import numpy as np
import tensorflow as tf

from tensorflow_privacy.privacy.analysis import rdp_accountant


class TestGaussianMoments(tf.test.TestCase, parameterized.TestCase):
  #################################
  # HELPER FUNCTIONS:             #
  # Exact computations using      #
  # multi-precision arithmetic.   #
  #################################

  def _log_float_mp(self, x):
    # Convert multi-precision input to float log space.
    return float(log(x)) if x >= sys.float_info.min else -np.inf

  def _integral_mp(self, fn, bounds=(-inf, inf)):
    integral, _ = quad(fn, bounds, error=True, maxdegree=8)
    return integral

  def _distributions_mp(self, sigma, q):

    def _mu0(x):
      return npdf(x, mu=0, sigma=sigma)

    def _mu1(x):
      return npdf(x, mu=1, sigma=sigma)

    def _mu(x):
      return (1 - q) * _mu0(x) + q * _mu1(x)

    return _mu0, _mu  # Closure!

  def _mu1_over_mu0(self, x, sigma):
    # Closed-form expression for N(1, sigma^2) / N(0, sigma^2) at x.
    return exp((2 * x - 1) / (2 * sigma**2))

  def _mu_over_mu0(self, x, q, sigma):
    return (1 - q) + q * self._mu1_over_mu0(x, sigma)

  def _compute_a_mp(self, sigma, q, alpha):
    """Compute A_alpha for arbitrary alpha by numerical integration."""
    mu0, _ = self._distributions_mp(sigma, q)
    a_alpha_fn = lambda z: mu0(z) * self._mu_over_mu0(z, q, sigma)**alpha
    return self._integral_mp(a_alpha_fn)

  # TEST ROUTINES
  def test_compute_heterogeneous_rdp_different_sampling_probabilities(self):
    sampling_probabilities = [0, 1]
    noise_multipliers = [10, 10]
    steps_list = [1, 1]
    orders = 20
    self.assertEqual(
        rdp_accountant.compute_heterogeneous_rdp(sampling_probabilities,
                                                 noise_multipliers, steps_list,
                                                 orders), 0.1)

  def test_compute_rdp_no_data(self):
    # q = 0
    self.assertEqual(rdp_accountant.compute_rdp(0, 10, 1, 20), 0)

  def test_compute_rdp_no_sampling(self):
    # q = 1, RDP = alpha/2 * sigma^2
    self.assertEqual(rdp_accountant.compute_rdp(1, 10, 1, 20), 0.1)

  def test_compute_rdp_scalar(self):
    rdp_scalar = rdp_accountant.compute_rdp(0.1, 2, 10, 5)
    self.assertAlmostEqual(rdp_scalar, 0.07737, places=5)

  def test_compute_rdp_sequence_without_replacement(self):
    rdp_vec = rdp_accountant.compute_rdp_sample_without_replacement(
        0.01, 2.5, 50, [1.001, 1.5, 2.5, 5, 50, 100, 256, 512, 1024, np.inf])
    self.assertAllClose(
        rdp_vec, [
            3.4701e-3, 3.4701e-3, 4.6386e-3, 8.7634e-3, 9.8474e-2, 1.6776e2,
            7.9297e2, 1.8174e3, 3.8656e3, np.inf
        ],
        rtol=1e-4)

  def test_compute_rdp_sequence(self):
    rdp_vec = rdp_accountant.compute_rdp(0.01, 2.5, 50,
                                         [1.5, 2.5, 5, 50, 100, np.inf])
    self.assertAllClose(
        rdp_vec,
        [6.5007e-04, 1.0854e-03, 2.1808e-03, 2.3846e-02, 1.6742e+02, np.inf],
        rtol=1e-4)

  params = ({
      'q': 1e-7,
      'sigma': .1,
      'order': 1.01
  }, {
      'q': 1e-6,
      'sigma': .1,
      'order': 256
  }, {
      'q': 1e-5,
      'sigma': .1,
      'order': 256.1
  }, {
      'q': 1e-6,
      'sigma': 1,
      'order': 27
  }, {
      'q': 1e-4,
      'sigma': 1.,
      'order': 1.5
  }, {
      'q': 1e-3,
      'sigma': 1.,
      'order': 2
  }, {
      'q': .01,
      'sigma': 10,
      'order': 20
  }, {
      'q': .1,
      'sigma': 100,
      'order': 20.5
  }, {
      'q': .99,
      'sigma': .1,
      'order': 256
  }, {
      'q': .999,
      'sigma': 100,
      'order': 256.1
  })

  # pylint:disable=undefined-variable
  @parameterized.parameters(iter(params))
  def test_compute_log_a_equals_mp(self, q, sigma, order):
    # Compare the cheap computation of log(A) with an expensive, multi-precision
    # computation.
    log_a = rdp_accountant._compute_log_a(q, sigma, order)
    log_a_mp = self._log_float_mp(self._compute_a_mp(sigma, q, order))
    np.testing.assert_allclose(log_a, log_a_mp, rtol=1e-4)

  def test_get_privacy_spent_check_target_delta(self):
    orders = range(2, 33)
    rdp = [1.1 for _ in orders]
    eps, _, opt_order = rdp_accountant.get_privacy_spent(
        orders, rdp, target_delta=1e-5)
    # Since rdp is constant, it should always pick the largest order.
    self.assertEqual(opt_order, 32)
    # Knowing the optimal order, we can calculate eps by hand.
    self.assertAlmostEqual(eps, 1.32783806176)

    # Second test for Gaussian noise (with no subsampling):
    orders = [0.001 * i for i in range(1000, 100000)
             ]  # Pick fine set of orders.
    rdp = rdp_accountant.compute_rdp(1, 4.530877117, 1, orders)
    # Scale is chosen to obtain exactly (1,1e-6)-DP.
    eps, _, _ = rdp_accountant.get_privacy_spent(orders, rdp, target_delta=1e-6)
    self.assertAlmostEqual(eps, 1)

  def test_get_privacy_spent_check_target_eps(self):
    orders = range(2, 33)
    rdp = [1.1 for _ in orders]
    _, delta, opt_order = rdp_accountant.get_privacy_spent(
        orders, rdp, target_eps=1.32783806176)
    # Since rdp is constant, it should always pick the largest order.
    self.assertEqual(opt_order, 32)
    self.assertAlmostEqual(delta, 1e-5)

    # Second test for Gaussian noise (with no subsampling):
    orders = [0.001 * i for i in range(1000, 100000)]  # Pick fine set of order.
    rdp = rdp_accountant.compute_rdp(1, 4.530877117, 1, orders)
    # Scale is chosen to obtain exactly (1,1e-6)-DP.
    _, delta, _ = rdp_accountant.get_privacy_spent(orders, rdp, target_eps=1)
    self.assertAlmostEqual(delta, 1e-6)

  def test_check_composition(self):
    orders = (1.25, 1.5, 1.75, 2., 2.5, 3., 4., 5., 6., 7., 8., 10., 12., 14.,
              16., 20., 24., 28., 32., 64., 256.)

    rdp = rdp_accountant.compute_rdp(
        q=1e-4, noise_multiplier=.4, steps=40000, orders=orders)

    eps, _, _ = rdp_accountant.get_privacy_spent(orders, rdp, target_delta=1e-6)

    rdp += rdp_accountant.compute_rdp(
        q=0.1, noise_multiplier=2, steps=100, orders=orders)
    eps, _, _ = rdp_accountant.get_privacy_spent(orders, rdp, target_delta=1e-5)
    # These tests use the old RDP -> approx DP conversion
    # self.assertAlmostEqual(eps, 8.509656, places=5)
    # self.assertEqual(opt_order, 2.5)
    # But these still provide an upper bound
    self.assertLessEqual(eps, 8.509656)

  def test_get_privacy_spent_consistency(self):
    orders = range(2, 50)  # Large range of orders (helps test for overflows).
    for q in [0.01, 0.1, 0.8, 1.]:  # Different subsampling rates.
      for multiplier in [0.1, 1., 3., 10., 100.]:  # Different noise scales.
        rdp = rdp_accountant.compute_rdp(q, multiplier, 1, orders)
        for delta in [.9, .5, .1, .01, 1e-3, 1e-4, 1e-5, 1e-6, 1e-9, 1e-12]:
          eps1, delta1, ord1 = rdp_accountant.get_privacy_spent(
              orders, rdp, target_delta=delta)
          eps2, delta2, ord2 = rdp_accountant.get_privacy_spent(
              orders, rdp, target_eps=eps1)
          self.assertEqual(delta1, delta)
          self.assertEqual(eps2, eps1)
          if eps1 != 0:
            self.assertEqual(ord1, ord2)
            self.assertAlmostEqual(delta, delta2)
          else:  # This is a degenerate case; we won't have consistency.
            self.assertLessEqual(delta2, delta)

  def test_get_privacy_spent_gaussian(self):
    # Compare the optimal bound for Gaussian with the one derived from RDP.
    # Also compare the RDP upper bound with the "standard" upper bound.
    orders = [0.1 * x for x in range(10, 505)]
    eps_vec = [0.1 * x for x in range(500)]
    rdp = rdp_accountant.compute_rdp(1, 1, 1, orders)
    for eps in eps_vec:
      _, delta, _ = rdp_accountant.get_privacy_spent(
          orders, rdp, target_eps=eps)
      # For comparison, we compute the optimal guarantee for Gaussian
      # using https://arxiv.org/abs/1805.06530 Theorem 8 (in v2).
      delta0 = math.erfc((eps - .5) / math.sqrt(2)) / 2
      delta0 = delta0 - math.exp(eps) * math.erfc((eps + .5) / math.sqrt(2)) / 2
      self.assertLessEqual(delta0, delta + 1e-300)  # need tolerance 10^-300

      # Compute the "standard" upper bound, which should be an upper bound.
      # Note, if orders is too sparse, this will NOT be an upper bound.
      delta1 = math.exp(-0.5 * (eps - 0.5)**2) if eps >= 0.5 else 1
      self.assertLessEqual(delta, delta1 + 1e-300)


class TreeAggregationTest(tf.test.TestCase, parameterized.TestCase):

  @parameterized.named_parameters(('eps20', 1.13, 19.74), ('eps2', 8.83, 2.04))
  def test_compute_eps_tree(self, noise_multiplier, eps):
    orders = [1 + x / 10. for x in range(1, 100)] + list(range(12, 64))
    # This tests is based on the StackOverflow setting in "Practical and
    # Private (Deep) Learning without Sampling or Shuffling". The calculated
    # epsilon could be better as the method in this package keeps improving.
    steps_list, target_delta = 1600, 1e-6
    rdp = rdp_accountant.compute_rdp_tree_restart(noise_multiplier, steps_list,
                                                  orders)
    new_eps = rdp_accountant.get_privacy_spent(
        orders, rdp, target_delta=target_delta)[0]
    self.assertLess(new_eps, eps)

  @parameterized.named_parameters(
      ('restart4', [400] * 4),
      ('restart2', [800] * 2),
      ('adaptive', [10, 400, 400, 400, 390]),
  )
  def test_compose_tree_rdp(self, steps_list):
    noise_multiplier, orders = 0.1, 1
    rdp_list = [
        rdp_accountant.compute_rdp_tree_restart(noise_multiplier, steps, orders)
        for steps in steps_list
    ]
    rdp_composed = rdp_accountant.compute_rdp_tree_restart(
        noise_multiplier, steps_list, orders)
    self.assertAllClose(rdp_composed, sum(rdp_list), rtol=1e-12)

  @parameterized.named_parameters(
      ('restart4', [400] * 4),
      ('restart2', [800] * 2),
      ('adaptive', [10, 400, 400, 400, 390]),
  )
  def test_compute_eps_tree_decreasing(self, steps_list):
    # Test privacy epsilon decreases with noise multiplier increasing when
    # keeping other parameters the same.
    orders = [1 + x / 10. for x in range(1, 100)] + list(range(12, 64))
    target_delta = 1e-6
    prev_eps = rdp_accountant.compute_rdp_tree_restart(0, steps_list, orders)
    for noise_multiplier in [0.1 * x for x in range(1, 100, 5)]:
      rdp = rdp_accountant.compute_rdp_tree_restart(noise_multiplier,
                                                    steps_list, orders)
      eps = rdp_accountant.get_privacy_spent(
          orders, rdp, target_delta=target_delta)[0]
      self.assertLess(eps, prev_eps)

  @parameterized.named_parameters(
      ('negative_noise', -1, 3, 1),
      ('empty_steps', 1, [], 1),
      ('negative_steps', 1, -3, 1),
  )
  def test_compute_rdp_tree_restart_raise(self, noise_multiplier, steps_list,
                                          orders):
    with self.assertRaisesRegex(ValueError, 'must be'):
      rdp_accountant.compute_rdp_tree_restart(noise_multiplier, steps_list,
                                              orders)

  @parameterized.named_parameters(
      ('t100n0.1', 100, 0.1),
      ('t1000n0.01', 1000, 0.01),
  )
  def test_no_tree_no_sampling(self, total_steps, noise_multiplier):
    orders = [1 + x / 10. for x in range(1, 100)] + list(range(12, 64))
    tree_rdp = rdp_accountant.compute_rdp_tree_restart(noise_multiplier,
                                                       [1] * total_steps,
                                                       orders)
    rdp = rdp_accountant.compute_rdp(1., noise_multiplier, total_steps, orders)
    self.assertAllClose(tree_rdp, rdp, rtol=1e-12)


if __name__ == '__main__':
  tf.test.main()
